from __future__ import annotations

"""数据采集 Pipeline（M15 — Orchestrator 架构）

七数据源各自独立采集 → 各取 Top-N → 摘要快速入库 → 后台 PDF 补全

架构（M15 重构）：
  采集层：7 个独立爬虫（BaseCrawler 子类，装配见 composition.py 的 crawler_factories）
  编排层：IngestionOrchestrator 统一调度爬虫 → 内容丰富 → 三库写入
  入库层：PostgreSQL + Milvus + Neo4j

  关键改进：
  - 爬虫与编排解耦：crawlers/*.py 各自封装采集逻辑，pipeline.py 只做编排
  - 新增 run_single_source()：支持按源独立调度（Phase 4 智能调度器需要）
  - 公开入口由应用组合根显式提供依赖，避免隐式进程级仓储回退

M14 变更（已保留）：
  - Arxiv 两阶段：摘要快速入库 → 后台异步 PDF 补全
  - 排行快照写入 document_rank_snapshots 表
"""

import asyncio
import logging
import threading
from datetime import date
from typing import Any, Callable, Dict, List, Optional

from backend.app.repositories.document_repository import (
    DocumentSearchReader,
    DocumentWriter,
)
from backend.app.repositories.rank_snapshot_repository import RankSnapshotRepository
from backend.app.repositories.task_repository import (
    LatestTaskReader,
)
from backend.app.services.ingestion.base_crawler import (
    BaseCrawler,
    today_cst,
)
from backend.app.services.ingestion.composition import IngestionDependencies
from backend.app.services.ingestion.content_enricher import enrich_papers
from backend.app.services.ingestion.document_projection import (
    document_id as _doc_id,
    paper_identity_keys as _paper_identity_keys,
    select_top_for_write,
)
from backend.app.services.ingestion.persistence_adapter import (
    IngestionPersistenceAdapter,
    IngestionPersistenceResult,
)
from backend.app.services.ingestion.source_orchestration import (
    MultiSourceIngestionRuntime,
)

logger = logging.getLogger(__name__)

# 后台 Arxiv PDF 线程注册表：服务进程内线程随进程常驻（daemon 语义无影响）；
# CLI（run_ingestion.py）路径在退出前经 join_background_pdf_threads 等待，
# 避免 main() 返回后 daemon 线程被进程杀掉导致 PDF 落盘/向量化中断。
_BACKGROUND_PDF_THREADS: List[threading.Thread] = []


def join_background_pdf_threads(timeout: float | None = None) -> None:
    """等待所有已启动的后台 PDF 线程结束（CLI 退出前调用）。"""
    pending = [t for t in _BACKGROUND_PDF_THREADS if _thread_alive(t)]
    if not pending:
        return
    logger.info("[Pipeline] 等待 %d 个后台 PDF 线程结束...", len(pending))
    for thread in pending:
        thread.join(timeout)
    still_alive = [getattr(t, "name", "?") for t in pending if _thread_alive(t)]
    if still_alive:
        logger.warning("[Pipeline] 后台 PDF 线程未在时限内结束: %s", still_alive)
    else:
        logger.info("[Pipeline] 后台 PDF 线程已全部结束。")


def _thread_alive(thread: object) -> bool:
    """鸭子类型判定：测试以 FakeThread 替身替换 threading.Thread。"""
    is_alive = getattr(thread, "is_alive", None)
    return bool(is_alive()) if callable(is_alive) else True


# ── 采集配置 ──────────────────────────────────────────────────────────────────
# 广撒网：每源多抓，后续通过 AI 评分筛选
_FETCH_LIMIT = 25
# 每个数据源独立保留的 Top-N 精华数量
_TOP_N_PER_SOURCE = 10
# 按源覆盖 Top-N：X 看板展示当天全部推文，入库保留全量（=抓取上限）；
# 其余源保持 Top-10。键为纯源名（crawler.source_name）。
_TOP_N_BY_SOURCE: Dict[str, int] = {"x": _FETCH_LIMIT}


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
    task_id: int,
    source_label: str,
    snapshot_date: Optional[str] = None,
    *,
    document_writer: DocumentWriter,
    rank_snapshots: RankSnapshotRepository,
    vector_writer_factory: Callable[[], object],
    graph_extractor_factory: Callable[[], object],
    graph_writer_factory: Callable[[], object],
) -> IngestionPersistenceResult:
    del task_id
    adapter = IngestionPersistenceAdapter(
        documents=document_writer,
        rank_snapshots=rank_snapshots,
        vector_writer_factory=vector_writer_factory,
        graph_extractor_factory=graph_extractor_factory,
        graph_writer_factory=graph_writer_factory,
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
        dependencies = provide_ingestion_dependencies(repositories=repositories)
        orchestrator = IngestionOrchestrator(dependencies)
        stats = orchestrator.run_all()                      # 全量采集
        stats = orchestrator.run_single_source("github")    # 单源调度
    """

    def __init__(
        self,
        dependencies: IngestionDependencies,
        *,
        limit: int = _FETCH_LIMIT,
        top_n: int = _TOP_N_PER_SOURCE,
        top_n_by_source: Optional[Dict[str, int]] = None,
        target_date: Optional[str] = None,
    ):
        self.limit = limit
        self.top_n = top_n
        self.top_n_by_source = (
            top_n_by_source if top_n_by_source is not None else _TOP_N_BY_SOURCE
        )
        self.target_date = target_date
        self.snapshot_date = target_date or today_cst()

        self.dependencies = dependencies
        self.repositories = dependencies.repositories
        self.documents = self.repositories.documents
        self.rank_snapshots = self.repositories.rank_snapshots
        self.github_ingestion = self.repositories.github_ingestion
        self.task_writer = dependencies.task_writer
        self._cache_invalidator = dependencies.cache_invalidator

        # 按工厂隔离构造：单个源的构造失败（如可插拔源插件缺失抛
        # XTransportUnavailable）只下线该源，不得拖死其他源的采集。
        # 失败记录在 crawler_construction_errors，run_single_source 命中
        # 未知源时将其带上，保持失败响亮可定位。
        self._crawlers: Dict[str, BaseCrawler] = {}
        self._crawler_construction_errors: List[str] = []
        for factory in dependencies.crawler_factories:
            try:
                crawler = factory()
            except Exception as exc:
                factory_name = getattr(factory, "__qualname__", repr(factory))
                logger.error(
                    "[Orchestrator] 爬虫工厂 %s 构造失败，跳过该源（不影响其他源）: %s",
                    factory_name,
                    exc,
                    exc_info=True,
                )
                self._crawler_construction_errors.append(f"{factory_name}: {exc}")
                continue
            self._crawlers[crawler.source_name] = crawler

    @property
    def crawler_construction_errors(self) -> List[str]:
        """构造期被跳过的源的失败原因（getattr 兜底：测试以 __new__ 构造）。"""
        return getattr(self, "_crawler_construction_errors", [])

    @property
    def registered_sources(self) -> List[str]:
        """返回所有已注册的数据源名称。"""
        return list(self._crawlers.keys())

    def _effective_top_n(self, source_name: str) -> int:
        """返回指定源的 Top-N：按源覆盖优先，未映射回落全局 top_n。

        getattr 兜底：部分测试以 __new__ 构造 orchestrator 不设该属性。
        """
        overrides = getattr(self, "top_n_by_source", None) or _TOP_N_BY_SOURCE
        return overrides.get(source_name, self.top_n)

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
    ) -> IngestionPersistenceResult:
        """内容丰富 → 三库写入，返回入库数量与新 X 文档行数。

        Args:
            source_name: 纯数据源名称（"arxiv" / "github" / ...），用于 _ENRICH_MAP 查找
            papers:      paper dict 列表
            task_id:     任务 ID
            log_label:   日志标签（可选，默认与 source_name 相同，可传 "arxiv_daily" 等）
        """
        label = log_label or source_name
        if not papers:
            logger.info("[Orchestrator][%s] 无原始数据，跳过。", label)
            return IngestionPersistenceResult(0)

        logger.info(
            "[Orchestrator][%s] %d 条 → 内容丰富...",
            label,
            len(papers),
        )

        if source_name == "x":
            # X rolling-window ingestion is completeness-first: the crawler has
            # already filtered, deduplicated, and timeline-sorted the full UTC
            # window. Reapplying engagement Top-N here would silently recreate
            # the old low-interaction tweet loss.
            selected = list(papers)
        else:
            selected = _select_top(
                papers,
                top_n=self._effective_top_n(source_name),
                source_label=label,
            )
        selected = _apply_existing_summary_short_circuit(
            selected,
            self.documents,
            label,
        )
        # source_name 是纯名称（如 "arxiv"），用于 _ENRICH_MAP 查找
        enrich_delay = 0.0 if source_name == "arxiv" else 0.5
        selected = await enrich_papers(
            selected,
            source_key=source_name,  # ← 修复 Bug1：传纯名称，不拼接 period
            delay=enrich_delay,
        )
        result = await asyncio.to_thread(
            _ingest_documents,
            selected,
            task_id,
            label,
            snapshot_date or self.snapshot_date,
            document_writer=self.documents,
            rank_snapshots=self.rank_snapshots,
            vector_writer_factory=self.dependencies.vector_writer_factory,
            graph_extractor_factory=self.dependencies.graph_extractor_factory,
            graph_writer_factory=self.dependencies.graph_writer_factory,
        )
        if source_name == "x" and self.dependencies.x_translation_processor is not None:
            try:
                await asyncio.to_thread(self.dependencies.x_translation_processor().process)
            except Exception as exc:
                logger.warning("[Orchestrator][x] 翻译处理失败（不影响采集）: %s", exc)
        return result

    def _start_arxiv_pdf_background(self, papers: List[dict]) -> None:
        """启动后台线程：下载 Arxiv PDF 落盘 → pdfplumber / pypdf 解析 → 切片写入 Milvus（非阻塞）。

        经组合的 pdf_indexer（ArxivPdfDownloader）执行：
          - 每篇 PDF 下载间隔 3s（防封杀）
          - 串行下载（max_workers=1）
          - 落盘到 storage/papers/{arxiv_id}.pdf
          - 更新关系数据库 documents.local_pdf_path
        """
        # 过滤出有 arxiv_id 的论文（不再依赖 pdf_pending 标记，因为已修复 enricher）
        arxiv_papers = [p for p in papers if p.get("arxiv_id") and p.get("pdf_url")]
        if not arxiv_papers:
            return

        logger.info(
            "[Orchestrator] 启动后台线程：落盘 + 向量化 %d 篇 Arxiv PDF...",
            len(arxiv_papers),
        )

        documents = self.documents  # 传引用给后台线程

        def _bg_pdf_download():
            try:
                milvus_repo = self.dependencies.pdf_vector_writer_factory()
                dl_ok, idx_ok = self.dependencies.pdf_indexer(
                    arxiv_papers,
                    milvus_repo=milvus_repo,
                    document_writer=documents,
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
        # 清理已结束的句柄后登记，供 CLI 路径退出前 join
        _BACKGROUND_PDF_THREADS[:] = [t for t in _BACKGROUND_PDF_THREADS if _thread_alive(t)]
        _BACKGROUND_PDF_THREADS.append(bg_thread)
        logger.info("[Orchestrator] 后台 PDF 下载线程已启动（daemon=True）。")

    async def _clear_dashboard_cache(self, *, new_x_rows: int = 0) -> None:
        if new_x_rows > 0:
            await self._cache_invalidator(new_x_rows=new_x_rows)
        else:
            await self._cache_invalidator()

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
# 公开 API（显式依赖入口）
# ═══════════════════════════════════════════════════════════════════════════════


def _require_dependencies(
    dependencies: IngestionDependencies | None,
    entrypoint: str,
) -> IngestionDependencies:
    if dependencies is None:
        raise TypeError(f"{entrypoint} requires explicit dependencies")
    return dependencies


def _compose_ingestion_orchestrator(
    *,
    limit: int,
    top_n: int,
    target_date: Optional[str],
    dependencies: IngestionDependencies,
) -> IngestionOrchestrator:
    return IngestionOrchestrator(
        dependencies=dependencies,
        limit=limit,
        top_n=top_n,
        target_date=target_date,
    )


def _run_ingestion_pipeline_with_dependencies(
    dependencies: IngestionDependencies,
    *,
    limit: int,
    top_n: int = _TOP_N_PER_SOURCE,
    target_date: Optional[str] = None,
) -> Dict[str, int]:
    orchestrator = _compose_ingestion_orchestrator(
        limit=limit,
        top_n=top_n,
        target_date=target_date,
        dependencies=dependencies,
    )
    return asyncio.run(orchestrator.run_all())


def run_ingestion_pipeline(
    limit: int = _FETCH_LIMIT,
    top_n: int = _TOP_N_PER_SOURCE,
    target_date: Optional[str] = None,
    *,
    dependencies: IngestionDependencies | None = None,
) -> Dict[str, int]:
    """运行全量采集 Pipeline（显式依赖入口）。

    委托给 IngestionOrchestrator.run_all()，保持外部调用接口不变；
    公开入口由应用组合根显式提供依赖，避免隐式进程级仓储回退。

    Args:
        limit: 每源最多抓取条数（初始广撒网）
        top_n: 每源最终保留入库的 Top-N 数量
        target_date: 可选，格式 YYYY-MM-DD。指定后作为快照日期和各源的基准日期。
        dependencies: 由应用组合根提供的采集依赖。

    Returns:
        各数据源的最终入库数量字典，包含 ingested_total 键。
    """
    return _run_ingestion_pipeline_with_dependencies(
        _require_dependencies(dependencies, "run_ingestion_pipeline"),
        limit=limit,
        top_n=top_n,
        target_date=target_date,
    )


def run_single_source_pipeline(
    source_name: str,
    limit: int = _FETCH_LIMIT,
    top_n: int = _TOP_N_PER_SOURCE,
    target_date: Optional[str] = None,
    periods: Optional[List[str]] = None,
    *,
    dependencies: IngestionDependencies | None = None,
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
    orchestrator = _compose_ingestion_orchestrator(
        limit=limit,
        top_n=top_n,
        target_date=target_date,
        dependencies=_require_dependencies(dependencies, "run_single_source_pipeline"),
    )
    return asyncio.run(orchestrator.run_single_source(source_name, periods=periods))


async def run_ingestion_pipeline_async(
    limit: int = _FETCH_LIMIT,
    top_n: int = _TOP_N_PER_SOURCE,
    target_date: Optional[str] = None,
    *,
    dependencies: IngestionDependencies | None = None,
) -> Dict[str, int]:
    """异步入口。"""
    orchestrator = _compose_ingestion_orchestrator(
        limit=limit,
        top_n=top_n,
        target_date=target_date,
        dependencies=_require_dependencies(dependencies, "run_ingestion_pipeline_async"),
    )
    return await orchestrator.run_all()


async def run_single_source_async(
    source_name: str,
    limit: int = _FETCH_LIMIT,
    top_n: int = _TOP_N_PER_SOURCE,
    target_date: Optional[str] = None,
    *,
    dependencies: IngestionDependencies | None = None,
) -> Dict[str, int]:
    """单源采集的异步版本。"""
    orchestrator = _compose_ingestion_orchestrator(
        limit=limit,
        top_n=top_n,
        target_date=target_date,
        dependencies=_require_dependencies(dependencies, "run_single_source_async"),
    )
    return await orchestrator.run_single_source(source_name)


def should_run_smart_ingestion(
    latest_task: dict[str, Any] | None,
    today: date,
) -> bool:
    """Return whether the latest task permits today's ingestion run."""
    if not latest_task or latest_task.get("status") != "success":
        return True

    # 零入库的 "success"（历史口径下全源失败也可能记 success + item_count=0）
    # 不算真正的成功，允许今天重试；item_count 缺失（旧行）保持原有判断。
    item_count = latest_task.get("item_count")
    if item_count is not None:
        try:
            if int(item_count) <= 0:
                return True
        except (TypeError, ValueError):
            pass

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
    if reader is None:
        raise TypeError("run_smart_ingestion requires explicit reader")
    if runner is None:
        raise TypeError("run_smart_ingestion requires explicit runner")
    _run_smart_ingestion_with(
        reader,
        runner,
        limit,
        date.today(),
    )
