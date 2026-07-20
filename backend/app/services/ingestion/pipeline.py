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
import hashlib
import logging
import threading
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi_cache import FastAPICache
from redis.asyncio import Redis

from langchain_core.documents import Document

from backend.app.repositories.graph_repo import GraphRepository
from backend.app.repositories.milvus_repo import MilvusRepository
from backend.app.repositories.mysql_repo import MySQLRepository
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


def _doc_id(paper: dict) -> str:
    """Generate a stable ID based on content identity (source + key fields).

    不包含 source_channel，确保同一篇文章在不同周期（daily/weekly/monthly）
    生成相同的 doc_id，从而支持 GREATEST() OR 语义的布尔字段 upsert。

    优先级：
      1. arxiv_id（+ source 前缀）
      2. GitHub full_name（+ source 前缀）
      3. url
      4. title hash（+ source 前缀）
    """
    source = paper.get("source", "")

    arxiv_id = paper.get("arxiv_id")
    if arxiv_id:
        return hashlib.md5(f"arxiv:{arxiv_id}".encode()).hexdigest()

    if source == "github":
        key = (
            paper.get("full_name")
            or paper.get("title")
            or paper.get("url")
            or str(paper)
        )
        return hashlib.md5(f"github:{key}".encode()).hexdigest()

    key = paper.get("url") or paper.get("title") or str(paper)
    return hashlib.md5(f"{source}:{key}".encode()).hexdigest()


def _to_documents(papers: List[dict]) -> List[Document]:
    """将原始 paper dict 列表转换为 LangChain Document 列表。"""
    documents: List[Document] = []
    for paper in papers:
        # stars 必须是 int（Milvus schema INT64），None 用 0 兜底，避免非 GitHub 源写入失败
        raw_stars = paper.get("stars")
        try:
            stars_val = int(raw_stars) if raw_stars is not None else 0
        except (TypeError, ValueError):
            stars_val = 0

        metadata = {
            "id": _doc_id(paper),
            "source": paper.get("source", "unknown"),
            "title": paper.get("title") or "",
            "published_date": paper.get("published_date") or "",
            "url": paper.get("url") or "",
            "pdf_url": paper.get("pdf_url") or "",
            # 源数据原始分（stars / likes 等），与 ai_score 区分
            "raw_score": float(paper.get("score") or 0.0),
            # Arxiv 渠道标记：hf_trending | arxiv_fallback
            "source_channel": paper.get("source_channel", paper.get("channel", ""))
            or "",
            # GitHub 专属字段（非 GitHub 源为 0/""，保持 schema 一致）
            "stars": stars_val,
            "language": paper.get("language") or "",
            "created_at": paper.get("created_at") or "",
            # 周期布尔字段：由 run_all / run_single_source 在 paper dict 上预设
            "in_daily": int(paper.get("in_daily", 0)),
            "in_weekly": int(paper.get("in_weekly", 0)),
            "in_monthly": int(paper.get("in_monthly", 0)),
        }
        # page_content 优先用 full_text（enricher 填充的完整正文），
        # 回退到 abstract → summary → title
        page_content = (
            paper.get("full_text")
            or paper.get("abstract")
            or paper.get("summary")
            or paper.get("title")
            or ""
        )
        documents.append(Document(page_content=page_content, metadata=metadata))
    return documents


def _paper_identity_keys(paper: dict) -> List[str]:
    keys: List[str] = []
    doc_id = _doc_id(paper)
    if doc_id:
        keys.append(f"id:{doc_id}")

    url = (paper.get("url") or "").strip()
    if url:
        keys.append(f"url:{url}")

    title = (paper.get("title") or "").strip()
    if title:
        keys.append(f"title:{title}")
    return keys


def _sort_papers_for_write(papers: List[dict]) -> List[dict]:
    return sorted(
        papers,
        key=lambda paper: (
            paper.get("source", ""),
            paper.get("source_channel", paper.get("channel", "")),
            paper.get("published_date", ""),
            _doc_id(paper),
        ),
    )


def _apply_existing_summary_short_circuit(
    papers: List[dict],
    db: MySQLRepository,
    source_label: str,
) -> List[dict]:
    if not papers:
        return papers

    existing = db.get_existing_document_summaries(
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
    """按 raw_score 降序取 Top-N（已移除 LLM 评分，直接使用原始热度分）。

    Args:
        papers: 原始 paper dict 列表
        top_n: 保留的 Top-N 数量
        source_label: 数据源标签（用于日志）

    Returns:
        按 raw_score 降序取 Top-N 的 paper dict 列表
    """
    if not papers:
        return []

    # 直接按 raw_score / score 降序，不再调用 LLM 评分
    papers.sort(
        key=lambda p: float(p.get("raw_score") or p.get("score") or 0),
        reverse=True,
    )
    selected = _sort_papers_for_write(papers[:top_n])

    logger.info(
        "[Pipeline][%s] Top-%d 筛选完成（raw_score: %s ~ %s）：",
        source_label,
        len(selected),
        (
            selected[-1].get("raw_score", selected[-1].get("score", "?"))
            if selected
            else "?"
        ),
        (
            selected[0].get("raw_score", selected[0].get("score", "?"))
            if selected
            else "?"
        ),
    )
    for i, p in enumerate(selected, 1):
        logger.info(
            "  #%d raw_score=%s | %s",
            i,
            p.get("raw_score", p.get("score", "?")),
            (p.get("title") or "")[:60],
        )

    return selected


def _ingest_documents(
    papers: List[dict],
    db: MySQLRepository,
    task_id: int,
    source_label: str,
    snapshot_date: Optional[str] = None,
) -> int:
    """将一批文档写入 SQLite + Milvus + Neo4j，返回成功入库数量。

    同时写入 document_rank_snapshots 表，记录当天的排行快照。
    """
    if not papers:
        logger.info("[Pipeline][%s] 无数据，跳过。", source_label)
        return 0

    # 快照日期：优先使用传入值，否则取 CST 当天日期
    if not snapshot_date:
        snapshot_date = today_cst()

    sorted_papers = _sort_papers_for_write(papers)
    documents = _to_documents(sorted_papers)

    # ── 替换式快照写入：先收集本批次涉及的所有 channel，逐 channel 清除旧快照 ──
    # 确保同一 snapshot_date + source_channel 下不会残留上次采集的旧 doc_id，
    # 避免 rank_in_period 重复导致旧论文覆盖新论文。
    channels_in_batch: set = set()
    for paper in sorted_papers:
        ch = paper.get("source_channel", paper.get("channel", ""))
        if ch:
            channels_in_batch.add(ch)

    for ch in channels_in_batch:
        try:
            deleted = db.delete_snapshots_by_channel(snapshot_date, ch)
            if deleted:
                logger.info(
                    "[Pipeline][%s] 清除旧快照 %s/%s: %d 条（将替换为本批 %d 条）",
                    source_label,
                    snapshot_date,
                    ch,
                    deleted,
                    len(sorted_papers),
                )
        except Exception as exc:
            logger.warning(
                "[Pipeline][%s] 清除旧快照失败 %s/%s: %s",
                source_label,
                snapshot_date,
                ch,
                exc,
            )

    # ── SQLite metadata + rank snapshot ────────────────────────────
    for paper, doc in zip(sorted_papers, documents):
        ai_score = doc.metadata.get("ai_score") or paper.get("ai_score")
        ai_reason = doc.metadata.get("ai_reason") or paper.get("ai_reason", "")
        raw_score = paper.get("raw_score", paper.get("score", 0.0))
        rank_in_period = int(paper.get("rank_in_period") or 9999)
        source_channel = paper.get("source_channel", paper.get("channel", ""))
        score_val = ai_score if ai_score is not None else 0.0

        db.upsert_document(
            {
                "id": doc.metadata["id"],
                "source": paper.get("source", source_label),
                "source_channel": source_channel,
                "title": paper.get("title"),
                "url": paper.get("url"),
                "summary": (paper.get("abstract") or paper.get("summary") or "")[:500],
                "published_date": paper.get("published_date"),
                "tags": paper.get("tags", []),
                "score": score_val,
                "raw_score": raw_score,
                "stars": doc.metadata.get("stars", 0),
                "forks": int(paper.get("forks") or doc.metadata.get("forks") or 0),
                "language": paper.get("language") or doc.metadata.get("language") or "",
                # 榜单内排名：1=第一名，值越小越靠前；未设置时默认 9999
                "rank_in_period": rank_in_period,
                "indexed": 1,
                # 周期布尔字段：GREATEST() 语义确保多周期 upsert 不丢失
                "in_daily": int(paper.get("in_daily", 0)),
                "in_weekly": int(paper.get("in_weekly", 0)),
                "in_monthly": int(paper.get("in_monthly", 0)),
            }
        )

        # ── 写入排行快照（历史记录，不会被后续采集覆盖） ──
        try:
            db.upsert_rank_snapshot(
                doc_id=doc.metadata["id"],
                snapshot_date=snapshot_date,
                source_channel=source_channel,
                rank_in_period=rank_in_period,
                raw_score=float(raw_score or 0.0),
                score=float(score_val or 0.0),
            )
        except Exception as exc:
            logger.warning(
                "[Pipeline][%s] 快照写入失败 doc_id=%s: %s",
                source_label,
                doc.metadata["id"],
                exc,
            )

    # ── Milvus vector indexing ─────────────────────────────────────
    try:
        milvus_repo = MilvusRepository()
        milvus_repo.add_documents(documents, already_split=False)
    except Exception as exc:
        logger.error("[Pipeline][%s] Milvus 写入失败: %s", source_label, exc)

    # ── Graph extraction + Neo4j ───────────────────────────────────
    # 只对 arxiv 源做图谱抽取；非 arxiv 来源跳过（向量检索已能覆盖）
    # 同时跳过数据库中已有记录的论文（existing_summary_reused=True），
    # 避免对重复爬取的论文重复消耗 LLM。
    is_arxiv_source = source_label.startswith("arxiv")
    if is_arxiv_source:
        # 筛选出真正新增的文档（旧文档复用 summary，无需重新抽图谱）
        new_doc_pairs = [
            (doc, paper)
            for doc, paper in zip(documents, sorted_papers)
            if not paper.get("existing_summary_reused", False)
        ]
        new_documents = [doc for doc, _ in new_doc_pairs]
        if new_documents:
            try:
                graph_extractor = GraphExtractor()
                graph_docs = graph_extractor.extract(new_documents)
                graph_repo = GraphRepository()
                graph_repo.add_graph_documents(graph_docs)
                graph_repo.close()
                logger.info(
                    "[Pipeline][%s] 图谱写入完成：%d 篇新论文（跳过 %d 篇已有记录）。",
                    source_label,
                    len(new_documents),
                    len(documents) - len(new_documents),
                )
            except Exception as exc:
                logger.error("[Pipeline][%s] Neo4j 写入失败: %s", source_label, exc)
        else:
            logger.info(
                "[Pipeline][%s] 图谱抽取跳过：所有 %d 篇论文均已存在于数据库。",
                source_label,
                len(documents),
            )
    else:
        logger.debug(
            "[Pipeline][%s] 非 arxiv 来源，跳过图谱抽取（向量检索已覆盖）。",
            source_label,
        )

    logger.info("[Pipeline][%s] 入库完成，%d 条。", source_label, len(sorted_papers))
    return len(sorted_papers)


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
    ):
        self.limit = limit
        self.top_n = top_n
        self.target_date = target_date
        self.snapshot_date = target_date or today_cst()

        self.db = MySQLRepository()

        # 实例化所有爬虫
        self._crawlers: Dict[str, BaseCrawler] = {}
        for cls in self._CRAWLER_CLASSES:
            crawler = cls()
            self._crawlers[crawler.source_name] = crawler

    @property
    def registered_sources(self) -> List[str]:
        """返回所有已注册的数据源名称。"""
        return list(self._crawlers.keys())

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
            self.db,
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
                    mysql_repo=db,
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

    async def run_single_source(
        self,
        source_name: str,
        periods: Optional[List[str]] = None,
    ) -> Dict[str, int]:
        """按源独立采集，按周期串行处理（Phase 4 智能调度器使用）。

        改造要点：
          - 按 daily → weekly → monthly 顺序逐周期采集
          - 每个周期独立设置布尔字段（in_daily / in_weekly / in_monthly）
          - 每个周期独立调用 _enrich_and_ingest()
          - 利用 GREATEST() upsert 语义合并多周期的布尔标记
        """
        crawler = self._crawlers.get(source_name)
        if crawler is None:
            raise ValueError(
                f"未知数据源 '{source_name}'，可用: {self.registered_sources}"
            )

        task_name = (
            f"single:{source_name}:{self.target_date}"
            if self.target_date
            else f"single:{source_name}"
        )
        task_id = self.db.create_task(task_name)
        total = 0
        arxiv_papers_for_pdf: List[dict] = []

        try:
            requested_periods = periods or ["daily", "weekly", "monthly"]
            for period in requested_periods:
                if period not in crawler.supported_periods:
                    logger.info(
                        "[Orchestrator][%s] 不支持 %s 周期，跳过。",
                        source_name,
                        period,
                    )
                    continue

                cr: CrawlResult = await crawler.fetch(
                    period=period,
                    limit=self.limit,
                    target_date=self.target_date,
                )

                if not cr.ok:
                    logger.warning(
                        "[Orchestrator][%s] %s 榜采集失败: %s",
                        source_name,
                        period,
                        cr.error,
                    )
                    continue

                if not cr.items:
                    logger.info(
                        "[Orchestrator][%s] %s 榜无数据。",
                        source_name,
                        period,
                    )
                    continue

                # 为该周期的 papers 设置布尔字段
                for p in cr.items:
                    p["in_daily"] = 1 if period == "daily" else 0
                    p["in_weekly"] = 1 if period == "weekly" else 0
                    p["in_monthly"] = 1 if period == "monthly" else 0

                if source_name == "github":
                    from backend.app.services.ingestion.github_hot_service import (
                        record_github_trending_hits,
                    )

                    hit_result = await asyncio.to_thread(
                        record_github_trending_hits,
                        cr.items,
                        period=period,
                        observed_date=cr.snapshot_date,
                        db=self.db,
                    )
                    if period == "daily" and hit_result["repo_ids"]:
                        from backend.app.services.ingestion.github_project_metrics_service import (
                            compute_github_daily_metrics,
                        )

                        metric_result = await asyncio.to_thread(
                            compute_github_daily_metrics,
                            metric_date=cr.snapshot_date,
                            repo_ids=hit_result["repo_ids"],
                        )
                        logger.info(
                            "[Orchestrator][github_daily] Trending 增长已同步：hits=%d metrics=%d fallback=%d",
                            hit_result["hits"],
                            metric_result["rows"],
                            metric_result["trending_fallback"],
                        )

                logger.info(
                    "[Orchestrator][%s] %s 榜采集 %d 条，开始 enrich+ingest...",
                    source_name,
                    period,
                    len(cr.items),
                )

                count = await self._enrich_and_ingest(
                    source_name=source_name,  # ← 修复 Bug1：传纯名称
                    papers=cr.items,
                    task_id=task_id,
                    log_label=f"{source_name}_{period}",  # 日志仍显示周期信息
                    snapshot_date=cr.snapshot_date,
                )
                total += count

                if source_name == "arxiv":
                    # 修复 Bug1：不再依赖 pdf_pending，直接收集有 arxiv_id 的论文
                    arxiv_papers_for_pdf.extend(
                        [p for p in cr.items if p.get("arxiv_id")]
                    )

            if source_name == "arxiv":
                self._start_arxiv_pdf_background(arxiv_papers_for_pdf)

            self.db.finish_task(task_id, status="success", item_count=total)
            try:
                await _clear_dashboard_cache_safely()
                logger.info(
                    "[Orchestrator] dashboard cache cleared after single-source ingest."
                )
            except Exception as exc:
                logger.warning(
                    "[Orchestrator] 清理 dashboard cache 失败（非致命）: %s", exc
                )
            logger.info(
                "[Orchestrator] 单源采集完成: %s → %d 条入库。",
                source_name,
                total,
            )

        except Exception as exc:
            self.db.finish_task(task_id, status="failed", error_msg=str(exc))
            logger.error("[Orchestrator] 单源采集失败 %s: %s", source_name, exc)
            raise

        return {source_name: total, "ingested_total": total}

    async def run_all(self) -> Dict[str, int]:
        """全量采集所有已注册数据源，按周期串行处理。

        改造要点（修复日榜/周榜数据缺失的根因）：
          - 按 daily → weekly → monthly 顺序串行处理
          - 每个周期内，各 crawler 并发采集（保留性能）
          - 每个周期的 papers 独立设置布尔字段并独立入库
          - 不再合并所有周期做全局 _select_top，避免月榜高分挤掉日榜数据
          - GREATEST() upsert 语义确保同一文章出现在多个周期时布尔字段被正确合并
        """
        task_name = (
            f"date_ingest:{self.target_date}"
            if self.target_date
            else "multi_source_ingest"
        )
        task_id = self.db.create_task(task_name)

        stats: Dict[str, int] = {name: 0 for name in self._crawlers}
        stats["huggingface"] = 0
        total = 0
        arxiv_papers_for_pdf: List[dict] = []

        try:
            logger.info(
                "[Orchestrator] 按周期串行采集 %d 个数据源（limit=%d, target_date=%s）...",
                len(self._crawlers),
                self.limit,
                self.target_date or "today",
            )

            for period in ("daily", "weekly", "monthly"):
                logger.info(
                    "[Orchestrator] ── 开始 %s 周期采集 ──",
                    period,
                )

                # 筛选支持当前周期的 crawler，并发采集
                period_crawl_tasks = {}
                for name, crawler in self._crawlers.items():
                    if period in crawler.supported_periods:
                        period_crawl_tasks[name] = crawler.fetch(
                            period=period,
                            limit=self.limit,
                            target_date=self.target_date,
                        )

                if not period_crawl_tasks:
                    logger.info(
                        "[Orchestrator] %s 周期无可用 crawler，跳过。",
                        period,
                    )
                    continue

                gathered = await asyncio.gather(
                    *period_crawl_tasks.values(),
                    return_exceptions=True,
                )

                # 逐源处理该周期的采集结果
                for source_key, crawl_result in zip(
                    period_crawl_tasks.keys(), gathered
                ):
                    if isinstance(crawl_result, Exception):
                        logger.error(
                            "[Orchestrator][%s] %s 榜采集异常: %s",
                            source_key,
                            period,
                            crawl_result,
                        )
                        continue

                    cr: CrawlResult = crawl_result
                    if not cr.ok:
                        logger.warning(
                            "[Orchestrator][%s] %s 榜采集失败: %s",
                            source_key,
                            period,
                            cr.error,
                        )
                        continue

                    if not cr.items:
                        logger.info(
                            "[Orchestrator][%s] %s 榜无数据。",
                            source_key,
                            period,
                        )
                        continue

                    # 为该周期的 papers 设置布尔字段
                    for p in cr.items:
                        p["in_daily"] = 1 if period == "daily" else 0
                        p["in_weekly"] = 1 if period == "weekly" else 0
                        p["in_monthly"] = 1 if period == "monthly" else 0

                    logger.info(
                        "[Orchestrator][%s] %s 榜采集 %d 条，开始 enrich+ingest...",
                        source_key,
                        period,
                        len(cr.items),
                    )

                    count = await self._enrich_and_ingest(
                        source_name=source_key,  # ← 修复 Bug1：传纯名称
                        papers=cr.items,
                        task_id=task_id,
                        log_label=f"{source_key}_{period}",  # 日志仍显示周期信息
                        snapshot_date=cr.snapshot_date,
                    )
                    stats[source_key] += count
                    total += count

                    if source_key == "arxiv":
                        # 修复 Bug1：不再依赖 pdf_pending，直接收集有 arxiv_id 的论文
                        arxiv_papers_for_pdf.extend(
                            [p for p in cr.items if p.get("arxiv_id")]
                        )

                logger.info(
                    "[Orchestrator] ── %s 周期处理完成 ──",
                    period,
                )

            self.db.finish_task(task_id, status="success", item_count=total)
            try:
                await _clear_dashboard_cache_safely()
                logger.info("[Orchestrator] dashboard cache cleared after full ingest.")
            except Exception as exc:
                logger.warning(
                    "[Orchestrator] 清理 dashboard cache 失败（非致命）: %s", exc
                )
            logger.info(
                "[Orchestrator] 采集完成，%d 源共 %d 条文档入库（按周期串行）。",
                len(self._crawlers),
                total,
            )

            self._start_arxiv_pdf_background(arxiv_papers_for_pdf)

        except Exception as exc:
            self.db.finish_task(task_id, status="failed", error_msg=str(exc))
            logger.error("[Orchestrator] ERROR: %s", exc)
            raise

        stats["ingested_total"] = total
        return stats


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


def run_smart_ingestion(limit: int = _FETCH_LIMIT) -> None:
    """智能采集：检测今天是否已有成功任务，若无则执行采集。"""
    db = MySQLRepository()
    today = date.today()

    try:
        latest = db.get_latest_task()
        if latest and latest.get("status") == "success":
            started_at = latest.get("started_at") or ""
            latest_task_date_str = started_at[:10]
            try:
                latest_task_date = date.fromisoformat(latest_task_date_str)
            except ValueError:
                latest_task_date = None

            if latest_task_date and latest_task_date >= today:
                logger.info(
                    "[SmartIngestion] 今天已成功采集（任务 #%d），无需重复。",
                    latest.get("id"),
                )
                return
    except Exception as exc:
        logger.warning("[SmartIngestion] 检查最新任务失败，继续执行: %s", exc)

    logger.info("[SmartIngestion] 执行今日采集，limit=%d ...", limit)
    try:
        run_ingestion_pipeline(limit=limit)
    except Exception as exc:
        logger.error("[SmartIngestion] 采集失败: %s", exc)
