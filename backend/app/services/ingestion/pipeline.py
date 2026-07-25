from __future__ import annotations

"""数据采集 Pipeline（M15 — Orchestrator 架构）

六数据源各自独立采集 → 各取 Top-N → 摘要快速入库 → 后台 PDF 补全

架构（M15 重构）：
  采集层：5 个独立爬虫（BaseCrawler 子类）+ HuggingFace（已禁用）
  编排层：IngestionOrchestrator 统一调度爬虫 → 内容丰富 → 三库写入
  入库层：SQLite + Milvus + Neo4j

  关键改进：
  - 爬虫与编排解耦：crawlers/*.py 各自封装采集逻辑，pipeline.py 只做编排
  - 新增 run_single_source()：支持按源独立调度（Phase 4 智能调度器需要）
  - 向后兼容：run_ingestion_pipeline() / run_smart_ingestion() 外部接口不变

M14 变更（已保留）：
  - Arxiv 两阶段：摘要快速入库 → 后台异步 PDF 补全
  - 排行快照写入 document_rank_snapshots 表
"""

import asyncio
import logging
import threading
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from fastapi_cache import FastAPICache
from redis.asyncio import Redis

from backend.app.core.config import settings
from backend.app.repositories.document_repository import (
    DocumentSearchReader,
    DocumentWriter,
)
from backend.app.repositories.graph_repo import GraphRepository
from backend.app.repositories.milvus_repo import MilvusRepository
from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.repositories.rank_snapshot_repository import RankSnapshotRepository
from backend.app.repositories.task_repository import (
    IngestionTaskWriter,
    LatestTaskReader,
)
from backend.app.services.ingestion.graph_extractor import GraphExtractor
from backend.app.services.ingestion.content_enricher import (
    enrich_papers,
    enrich_arxiv_pdfs_background,
)
from backend.app.services.ingestion.arxiv_pdf_downloader import (
    download_and_index_arxiv_pdfs,
)
from backend.app.services.ingestion.base_crawler import (
    BaseCrawler,
    CrawlResult,
    today_cst,
)
from backend.app.services.ingestion.crawlers import (
    ArxivCrawler,
    GitHubCrawler,
    NewsCrawler,
    ProductHuntCrawler,
    HackerNewsCrawler,
)
from backend.app.services.ingestion.document_projection import (
    document_id as _doc_id,
    paper_identity_keys as _paper_identity_keys,
    project_documents as _to_documents,
    select_top_for_write,
    sort_papers_for_write as _sort_papers_for_write,
)
from backend.app.services.ingestion.persistence_adapter import (
    IngestionPersistenceAdapter,
)
from backend.app.services.ingestion.source_orchestration import (
    MultiSourceIngestionRuntime,
)

logger = logging.getLogger(__name__)


async def _clear_dashboard_cache_safely() -> None:
    """清理 dashboard cache。

    避免直接复用 FastAPICache 在应用启动事件循环中初始化的 backend，
    从而触发 "Future attached to a different loop"。

    这里为当前协程所在 loop 临时创建一个短生命周期 Redis 客户端，
    使用多种 pattern 兜底清除 dashboard 缓存键——
    因为 FastAPICache._prefix 可能是私有属性取不到真实值，
    导致单一 pattern 无法匹配实际 key。
    """
    redis_client = Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        password=settings.redis_password or None,
        decode_responses=False,
    )
    try:
        # 尝试从 FastAPICache 取 prefix（可能为空字符串或私有属性不可达）
        _raw_prefix = getattr(FastAPICache, "_prefix", "") or ""

        # 多种 pattern 兜底：
        # 核心 prefix 是 main.py 中写死的 "aigc-cache:"，同时兼容其他情况
        patterns = list(
            dict.fromkeys(  # 去重同时保持顺序
                [
                    "aigc-cache:dashboard:*",  # 主路径：main.py 中配置的实际 prefix
                    f"{_raw_prefix}dashboard:*",  # FastAPICache 运行时取到的 prefix（可能与上方相同）
                    "dashboard:*",  # 无 prefix 情况
                    "*:dashboard:*",  # 任意 prefix 通配（最宽泛）
                ]
            )
        )

        total_deleted = 0
        for pattern in patterns:
            keys = await redis_client.keys(pattern)
            if keys:
                await redis_client.delete(*keys)
                total_deleted += len(keys)
                logger.info(
                    "[Orchestrator] dashboard cache: pattern=%r 删除 %d keys。",
                    pattern,
                    len(keys),
                )

        if total_deleted == 0:
            logger.info(
                "[Orchestrator] dashboard cache: 未找到可删除的 key（可能已过期）。"
            )
        else:
            logger.info(
                "[Orchestrator] dashboard cache cleared，共删除 %d keys。",
                total_deleted,
            )
    finally:
        close_method = getattr(redis_client, "aclose", None)
        if close_method is not None:
            await close_method()
        else:
            await redis_client.close()


# ── 采集配置 ──────────────────────────────────────────────────────────────────
# 广撒网：每源多抓，后续通过 AI 评分筛选
_FETCH_LIMIT = 25
# 每个数据源独立保留的 Top-N 精华数量
_TOP_N_PER_SOURCE = 10


def _apply_existing_summary_short_circuit(
    papers: List[dict],
    documents: DocumentSearchReader,
    source_label: str,
) -> List[dict]:
    if not papers:
        return papers

    existing = documents.get_existing_document_summaries(
        ids=[_doc_id(paper) for paper in papers],
        urls=[(paper.get("url") or "").strip() for paper in papers],
        titles=[(paper.get("title") or "").strip() for paper in papers],
    )
    if not existing:
        return papers

    skipped_count = 0
    for paper in papers:
        matched_summary = ""
        for key in _paper_identity_keys(paper):
            matched_summary = existing.get(key, "")
            if matched_summary:
                break
        if not matched_summary:
            continue

        skipped_count += 1
        paper["summary"] = matched_summary
        paper.setdefault("abstract", matched_summary)
        paper["full_text"] = matched_summary
        paper["skip_enrich"] = True
        paper["existing_summary_reused"] = True

    if skipped_count:
        logger.info(
            "[Pipeline][%s] 命中已有 summary，跳过 enrich: %d/%d 条",
            source_label,
            skipped_count,
            len(papers),
        )
    return papers


def _select_top(
    papers: List[dict],
    top_n: int = _TOP_N_PER_SOURCE,
    source_label: str = "unknown",
) -> List[dict]:
    selected = select_top_for_write(papers, top_n)
    if selected:
        logger.info(
            "[Pipeline][%s] Top-%d 筛选完成（raw_score: %s ~ %s）",
            source_label,
            len(selected),
            selected[-1].get("raw_score", selected[-1].get("score", "?")),
            selected[0].get("raw_score", selected[0].get("score", "?")),
        )
    return selected


def _ingest_documents(
    papers: List[dict],
    db: MySQLRepository,
    task_id: int,
    source_label: str,
    snapshot_date: Optional[str] = None,
    document_writer: DocumentWriter | None = None,
    rank_snapshots: RankSnapshotRepository | None = None,
) -> int:
    del task_id
    adapter = IngestionPersistenceAdapter(
        documents=document_writer or db.documents,
        rank_snapshots=rank_snapshots or db.rank_snapshots,
        vector_writer_factory=MilvusRepository,
        graph_extractor_factory=GraphExtractor,
        graph_writer_factory=GraphRepository,
    )
    return adapter.persist(
        papers,
        source_label=source_label,
        snapshot_date=snapshot_date or today_cst(),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# IngestionOrchestrator — M15 核心：轻量编排器
# ═══════════════════════════════════════════════════════════════════════════════


class IngestionOrchestrator:
    """轻量编排器：调度爬虫 → 内容丰富 → 三库写入。

    职责：
      - 管理所有已注册的爬虫实例
      - 提供 run_all() 和 run_single_source() 两种入口
      - 统一处理快照日期、内容丰富、后台 PDF 补全

    使用方式：
        orchestrator = IngestionOrchestrator()
        stats = orchestrator.run_all()                      # 全量采集
        stats = orchestrator.run_single_source("github")    # 单源调度
    """

    # 已注册的爬虫（按优先级排列）
    _CRAWLER_CLASSES: List[type] = [
        ArxivCrawler,
        GitHubCrawler,
        NewsCrawler,
        ProductHuntCrawler,
        HackerNewsCrawler,
    ]

    def __init__(
        self,
        limit: int = _FETCH_LIMIT,
        top_n: int = _TOP_N_PER_SOURCE,
        target_date: Optional[str] = None,
        task_writer: IngestionTaskWriter | None = None,
    ):
        self.limit = limit
        self.top_n = top_n
        self.target_date = target_date
        self.snapshot_date = target_date or today_cst()

        self.db = MySQLRepository()
        self.task_writer = task_writer or self.db.ingestion_tasks

        # 实例化所有爬虫
        self._crawlers: Dict[str, BaseCrawler] = {}
        for cls in self._CRAWLER_CLASSES:
            crawler = cls()
            self._crawlers[crawler.source_name] = crawler

    @property
    def registered_sources(self) -> List[str]:
        """返回所有已注册的数据源名称。"""
        return list(self._crawlers.keys())

    def _create_task(self, task_name: str) -> int:
        return self.task_writer.create_task(task_name)

    def _finish_task(
        self,
        task_id: int,
        *,
        status: str = "success",
        error_msg: str | None = None,
        item_count: int = 0,
    ) -> None:
        self.task_writer.finish_task(
            task_id,
            status=status,
            error_msg=error_msg,
            item_count=item_count,
        )

    async def _enrich_and_ingest(
        self,
        source_name: str,
        papers: List[dict],
        task_id: int,
        log_label: Optional[str] = None,
        snapshot_date: Optional[str] = None,
    ) -> int:
        """内容丰富 → 三库写入，返回入库数量。

        Args:
            source_name: 纯数据源名称（"arxiv" / "github" / ...），用于 _ENRICH_MAP 查找
            papers:      paper dict 列表
            task_id:     任务 ID
            log_label:   日志标签（可选，默认与 source_name 相同，可传 "arxiv_daily" 等）
        """
        label = log_label or source_name
        if not papers:
            logger.info("[Orchestrator][%s] 无原始数据，跳过。", label)
            return 0

        logger.info(
            "[Orchestrator][%s] %d 条 → 内容丰富...",
            label,
            len(papers),
        )

        selected = _select_top(
            papers,
            top_n=self.top_n,
            source_label=label,
        )
        selected = _apply_existing_summary_short_circuit(
            selected,
            self.db.documents,
            label,
        )
        # source_name 是纯名称（如 "arxiv"），用于 _ENRICH_MAP 查找
        enrich_delay = 0.0 if source_name == "arxiv" else 0.5
        selected = await enrich_papers(
            selected,
            source_key=source_name,  # ← 修复 Bug1：传纯名称，不拼接 period
            delay=enrich_delay,
        )
        count = await asyncio.to_thread(
            _ingest_documents,
            selected,
            self.db,
            task_id,
            label,
            snapshot_date or self.snapshot_date,
            self.db.documents,
            self.db.rank_snapshots,
        )
        return count

    def _start_arxiv_pdf_background(self, papers: List[dict]) -> None:
        """启动后台线程：下载 Arxiv PDF 落盘 → PyMuPDF 解析 → 切片写入 Milvus（非阻塞）。

        使用新的 ArxivPdfDownloader 替代旧的 enrich_arxiv_pdfs_background：
          - 每篇 PDF 下载间隔 3s（防封杀）
          - 串行下载（max_workers=1）
          - 落盘到 storage/papers/{arxiv_id}.pdf
          - 更新 MySQL local_pdf_path
        """
        # 过滤出有 arxiv_id 的论文（不再依赖 pdf_pending 标记，因为已修复 enricher）
        arxiv_papers = [p for p in papers if p.get("arxiv_id") and p.get("pdf_url")]
        if not arxiv_papers:
            return

        logger.info(
            "[Orchestrator] 启动后台线程：落盘 + 向量化 %d 篇 Arxiv PDF...",
            len(arxiv_papers),
        )

        db = self.db  # 传引用给后台线程

        def _bg_pdf_download():
            try:
                milvus_repo = MilvusRepository()
                dl_ok, idx_ok = download_and_index_arxiv_pdfs(
                    arxiv_papers,
                    milvus_repo=milvus_repo,
                    mysql_repo=db.documents,
                    sleep_between=3.0,
                    max_workers=1,
                )
                logger.info(
                    "[Orchestrator] 后台 PDF 下载完成：落盘 %d，向量化 %d。",
                    dl_ok,
                    idx_ok,
                )
            except Exception as exc:
                logger.error("[Orchestrator] 后台 PDF 下载线程异常: %s", exc)

        bg_thread = threading.Thread(
            target=_bg_pdf_download,
            name="arxiv-pdf-download",
            daemon=True,
        )
        bg_thread.start()
        logger.info("[Orchestrator] 后台 PDF 下载线程已启动（daemon=True）。")

    async def _clear_dashboard_cache(self) -> None:
        await _clear_dashboard_cache_safely()

    async def run_single_source(
        self,
        source_name: str,
        periods: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        """按源独立采集，保持既有公开入口与周期顺序。"""
        return await MultiSourceIngestionRuntime(self).run_single_source(
            source_name, periods
        )

    async def run_all(self) -> Dict[str, int]:
        """按 daily → weekly → monthly 调度所有已注册数据源。"""
        return await MultiSourceIngestionRuntime(self).run_all()


# ═══════════════════════════════════════════════════════════════════════════════
# 公开 API（向后兼容）
# ═══════════════════════════════════════════════════════════════════════════════


def run_ingestion_pipeline(
    limit: int = _FETCH_LIMIT,
    top_n: int = _TOP_N_PER_SOURCE,
    target_date: Optional[str] = None,
) -> Dict[str, int]:
    """运行全量采集 Pipeline（向后兼容入口）。

    委托给 IngestionOrchestrator.run_all()，保持外部调用接口不变。

    Args:
        limit: 每源最多抓取条数（初始广撒网）
        top_n: 每源最终保留入库的 Top-N 数量
        target_date: 可选，格式 YYYY-MM-DD。指定后作为快照日期和各源的基准日期。

    Returns:
        各数据源的最终入库数量字典，包含 ingested_total 键。
    """
    orchestrator = IngestionOrchestrator(
        limit=limit,
        top_n=top_n,
        target_date=target_date,
    )
    return asyncio.run(orchestrator.run_all())


def run_single_source_pipeline(
    source_name: str,
    limit: int = _FETCH_LIMIT,
    top_n: int = _TOP_N_PER_SOURCE,
    target_date: Optional[str] = None,
    periods: Optional[List[str]] = None,
) -> Dict[str, int]:
    """单源采集入口（Phase 4 调度器使用）。

    Args:
        source_name: 数据源名称（arxiv / github / news / producthunt / hackernews）
        limit: 每源最多抓取条数
        top_n: 每源保留的 Top-N 数量
        target_date: 可选快照日期

    Returns:
        {source_name: count, "ingested_total": count}
    """
    orchestrator = IngestionOrchestrator(
        limit=limit,
        top_n=top_n,
        target_date=target_date,
    )
    return asyncio.run(orchestrator.run_single_source(source_name, periods=periods))


async def run_ingestion_pipeline_async(
    limit: int = _FETCH_LIMIT,
    top_n: int = _TOP_N_PER_SOURCE,
    target_date: Optional[str] = None,
) -> Dict[str, int]:
    """异步入口。"""
    orchestrator = IngestionOrchestrator(
        limit=limit,
        top_n=top_n,
        target_date=target_date,
    )
    return await orchestrator.run_all()


async def run_single_source_async(
    source_name: str,
    limit: int = _FETCH_LIMIT,
    top_n: int = _TOP_N_PER_SOURCE,
    target_date: Optional[str] = None,
) -> Dict[str, int]:
    """单源采集的异步版本。"""
    orchestrator = IngestionOrchestrator(
        limit=limit,
        top_n=top_n,
        target_date=target_date,
    )
    return await orchestrator.run_single_source(source_name)


def should_run_smart_ingestion(
    latest_task: dict[str, Any] | None,
    today: date,
) -> bool:
    """Return whether the latest task permits today's ingestion run."""
    if not latest_task or latest_task.get("status") != "success":
        return True

    started_at = latest_task.get("started_at")
    if not isinstance(started_at, str):
        return True

    try:
        latest_task_date = date.fromisoformat(started_at[:10])
    except ValueError:
        return True

    return latest_task_date < today


def _run_smart_ingestion_with(
    reader: LatestTaskReader,
    runner: Callable[[int], Any],
    limit: int,
    today: date,
) -> None:
    try:
        latest = reader.get_latest_task()
        if not should_run_smart_ingestion(latest, today):
            logger.info(
                "[SmartIngestion] 今天已成功采集（任务 #%d），无需重复。",
                latest.get("id"),
            )
            return
    except Exception as exc:
        logger.warning("[SmartIngestion] 检查最新任务失败，继续执行: %s", exc)

    logger.info("[SmartIngestion] 执行今日采集，limit=%d ...", limit)
    try:
        runner(limit)
    except Exception as exc:
        logger.error("[SmartIngestion] 采集失败: %s", exc)


def run_smart_ingestion(
    limit: int = _FETCH_LIMIT,
    *,
    reader: LatestTaskReader | None = None,
    runner: Callable[[int], Any] | None = None,
) -> None:
    """智能采集：检测今天是否已有成功任务，若无则执行采集。"""
    _run_smart_ingestion_with(
        reader if reader is not None else MySQLRepository().ingestion_tasks,
        runner if runner is not None else run_ingestion_pipeline,
        limit,
        date.today(),
    )
