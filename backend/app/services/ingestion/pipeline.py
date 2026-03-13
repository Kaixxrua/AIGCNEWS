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

from langchain_core.documents import Document

from backend.app.repositories.graph_repo import GraphRepository
from backend.app.repositories.milvus_repo import MilvusRepository
from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.services.ingestion.graph_extractor import GraphExtractor
from backend.app.services.ingestion.content_enricher import (
    enrich_papers,
    enrich_arxiv_pdfs_background,
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

# ── 采集配置 ──────────────────────────────────────────────────────────────────
# 广撒网：每源多抓，后续通过 AI 评分筛选
_FETCH_LIMIT = 25
# 每个数据源独立保留的 Top-N 精华数量
_TOP_N_PER_SOURCE = 10


def _doc_id(paper: dict) -> str:
    """Generate a stable ID that preserves multi-period leaderboard entries.

    优先级：
      1. arxiv_id + source_channel
      2. GitHub full_name + source_channel
      3. url + source_channel
      4. title hash + source_channel
    """
    source = paper.get("source", "")
    source_channel = paper.get("source_channel") or paper.get("channel") or ""

    arxiv_id = paper.get("arxiv_id")
    if arxiv_id:
        return hashlib.md5(f"arxiv:{arxiv_id}:{source_channel}".encode()).hexdigest()

    if source == "github":
        key = (
            paper.get("full_name")
            or paper.get("title")
            or paper.get("url")
            or str(paper)
        )
        return hashlib.md5(f"github:{key}:{source_channel}".encode()).hexdigest()

    key = paper.get("url") or paper.get("title") or str(paper)
    return hashlib.md5(f"{key}:{source_channel}".encode()).hexdigest()


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
                # 榜单内排名：1=第一名，值越小越靠前；未设置时默认 9999
                "rank_in_period": rank_in_period,
                "indexed": 1,
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
    try:
        graph_extractor = GraphExtractor()
        graph_docs = graph_extractor.extract(documents)
        graph_repo = GraphRepository()
        graph_repo.add_graph_documents(graph_docs)
        graph_repo.close()
    except Exception as exc:
        logger.error("[Pipeline][%s] Neo4j 写入失败: %s", source_label, exc)

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
        source_key: str,
        papers: List[dict],
        task_id: int,
    ) -> int:
        """内容丰富 → 三库写入，返回入库数量。"""
        if not papers:
            logger.info("[Orchestrator][%s] 无原始数据，跳过。", source_key)
            return 0

        logger.info(
            "[Orchestrator][%s] %d 条 → 内容丰富...",
            source_key,
            len(papers),
        )

        selected = _select_top(
            papers,
            top_n=self.top_n,
            source_label=source_key,
        )
        selected = _apply_existing_summary_short_circuit(
            selected,
            self.db,
            source_key,
        )
        enrich_delay = 0.0 if source_key == "arxiv" else 0.5
        selected = await enrich_papers(
            selected,
            source_key=source_key,
            delay=enrich_delay,
        )
        count = await asyncio.to_thread(
            _ingest_documents,
            selected,
            self.db,
            task_id,
            source_key,
            self.snapshot_date,
        )
        return count

    def _start_arxiv_pdf_background(self, papers: List[dict]) -> None:
        """启动后台线程补全 Arxiv PDF（非阻塞）。"""
        arxiv_papers_for_pdf = [p for p in papers if p.get("pdf_pending")]
        if not arxiv_papers_for_pdf:
            return

        logger.info(
            "[Orchestrator] 启动后台线程：补全 %d 篇 Arxiv PDF...",
            len(arxiv_papers_for_pdf),
        )

        def _bg_pdf_enrich():
            try:
                milvus_repo = MilvusRepository()
                enrich_arxiv_pdfs_background(
                    arxiv_papers_for_pdf,
                    milvus_repo=milvus_repo,
                    delay=2.0,
                    max_workers=3,
                )
                logger.info("[Orchestrator] 后台 PDF 补全线程完成。")
            except Exception as exc:
                logger.error("[Orchestrator] 后台 PDF 补全线程异常: %s", exc)

        bg_thread = threading.Thread(
            target=_bg_pdf_enrich,
            name="arxiv-pdf-enrich",
            daemon=True,
        )
        bg_thread.start()
        logger.info("[Orchestrator] 后台 PDF 补全线程已启动（daemon=True）。")

    async def run_single_source(self, source_name: str) -> Dict[str, int]:
        """按源独立采集（Phase 4 智能调度器使用）。"""
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

        try:
            results = await crawler.fetch_all_periods(
                limit=self.limit,
                top_n=self.top_n,
                target_date=self.target_date,
            )

            all_items: List[dict] = []
            for result in results:
                if result.ok:
                    all_items.extend(result.items)
                else:
                    logger.warning(
                        "[Orchestrator][%s] %s 榜采集失败: %s",
                        source_name,
                        result.period,
                        result.error,
                    )

            total = await self._enrich_and_ingest(source_name, all_items, task_id)

            if source_name == "arxiv":
                self._start_arxiv_pdf_background(all_items)

            self.db.finish_task(task_id, status="success", item_count=total)
            try:
                await FastAPICache.clear(namespace="dashboard")
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
        """全量并行采集所有已注册数据源。"""
        task_name = (
            f"date_ingest:{self.target_date}"
            if self.target_date
            else "multi_source_ingest"
        )
        task_id = self.db.create_task(task_name)

        stats: Dict[str, int] = {name: 0 for name in self._crawlers}
        stats["huggingface"] = 0
        total = 0

        try:
            logger.info(
                "[Orchestrator] M15 并行采集 %d 个数据源（limit=%d, target_date=%s）...",
                len(self._crawlers),
                self.limit,
                self.target_date or "today",
            )

            crawl_tasks = {
                name: crawler.fetch_all_periods(
                    limit=self.limit,
                    top_n=self.top_n,
                    target_date=self.target_date,
                )
                for name, crawler in self._crawlers.items()
            }
            gathered = await asyncio.gather(
                *crawl_tasks.values(),
                return_exceptions=True,
            )

            raw_results: Dict[str, List[dict]] = {}
            for source_key, crawl_result in zip(crawl_tasks.keys(), gathered):
                if isinstance(crawl_result, Exception):
                    logger.error(
                        "[Orchestrator] %s 采集异常: %s",
                        source_key,
                        crawl_result,
                    )
                    raw_results[source_key] = []
                    continue

                all_items: List[dict] = []
                for cr in crawl_result:
                    if cr.ok:
                        all_items.extend(cr.items)
                    else:
                        logger.warning(
                            "[Orchestrator][%s] %s 榜采集失败: %s",
                            source_key,
                            cr.period,
                            cr.error,
                        )
                raw_results[source_key] = all_items
                logger.info(
                    "[Orchestrator] %s 采集完成，%d 条（合并后）。",
                    source_key,
                    len(all_items),
                )

            logger.info(
                "[Orchestrator] 开始逐源内容丰富 → 入库（%d 源）...",
                len(raw_results),
            )

            arxiv_papers_for_pdf: List[dict] = []
            for source_key in self._crawlers:
                papers = raw_results.get(source_key, [])
                count = await self._enrich_and_ingest(source_key, papers, task_id)
                stats[source_key] = count
                total += count
                if source_key == "arxiv":
                    arxiv_papers_for_pdf.extend(
                        [p for p in papers if p.get("pdf_pending")]
                    )

            self.db.finish_task(task_id, status="success", item_count=total)
            try:
                await FastAPICache.clear(namespace="dashboard")
                logger.info("[Orchestrator] dashboard cache cleared after full ingest.")
            except Exception as exc:
                logger.warning(
                    "[Orchestrator] 清理 dashboard cache 失败（非致命）: %s", exc
                )
            logger.info(
                "[Orchestrator] M15 采集完成，%d 源共 %d 条文档入库。",
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
    return asyncio.run(orchestrator.run_single_source(source_name))


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
