from __future__ import annotations

import json
import logging
from typing import Callable

from langchain_core.documents import Document

from backend.app.repositories.document_repository import DocumentWriter
from backend.app.repositories.rank_snapshot_repository import RankSnapshotRepository
from backend.app.services.ingestion.document_projection import (
    project_documents,
    sort_papers_for_write,
)

logger = logging.getLogger(__name__)

# 全天累积型快照 channel：同一 snapshot_date 内多轮采集取并集（X 看板展示
# 当天全部推文）。upsert 冲突键 (doc_id, snapshot_date, source_channel) 保留
# LEAST(rank_in_period)/GREATEST(raw_score, score)，天然幂等；删除推文仍经
# delete_document 级联删快照。其余 channel 保持整 channel 替换语义。
ACCUMULATE_SNAPSHOT_CHANNELS = frozenset({"x_daily_watchlist"})



def project_document_write(
    paper: dict,
    document: Document,
    source_label: str,
) -> dict:
    """Project one enriched item to the document repository write shape."""
    ai_score = document.metadata.get("ai_score") or paper.get("ai_score")
    score = ai_score if ai_score is not None else 0.0
    media = paper.get("media")
    quote = paper.get("quote")
    link_card = paper.get("link_card")
    source = paper.get("source", source_label)
    summary = paper.get("abstract") or paper.get("summary") or ""
    if source != "x":
        summary = summary[:500]
    # documents.title 为 VARCHAR(1024)：长文推文等超长标题截断防止写入越界
    title = paper.get("title")
    if isinstance(title, str) and len(title) > 1024:
        title = title[:1024]
    return {
        "id": document.metadata["id"],
        "source": source,
        "source_channel": paper.get(
            "source_channel", paper.get("channel", "")
        ),
        "title": title,
        "url": paper.get("url"),
        "summary": summary,
        "published_date": paper.get("published_date"),
        "published_at": paper.get("published_at"),
        "tags": paper.get("tags", []),
        "score": score,
        "raw_score": paper.get("raw_score", paper.get("score", 0.0)),
        "stars": document.metadata.get("stars", 0),
        "forks": int(paper.get("forks") or document.metadata.get("forks") or 0),
        "language": paper.get("language") or document.metadata.get("language") or "",
        "rank_in_period": int(paper.get("rank_in_period") or 9999),
        "indexed": 1,
        "in_daily": int(paper.get("in_daily", 0)),
        "in_weekly": int(paper.get("in_weekly", 0)),
        "in_monthly": int(paper.get("in_monthly", 0)),
        "media": json.dumps(media, ensure_ascii=False) if media else None,
        "quote": json.dumps(quote, ensure_ascii=False) if isinstance(quote, dict) else None,
        "link_card": json.dumps(link_card, ensure_ascii=False) if isinstance(link_card, dict) else None,
        "author_avatar_url": paper.get("author_avatar_url"),
        "author_name": paper.get("author_name"),
        "translation_zh": paper.get("translation_zh"),
        # arXiv 采集器产出 authors（≤5 字符串列表）与 arxiv_id；None/空值写 NULL，
        # upsert 冲突合并（COALESCE(NULLIF(...,''))）据此保留已有值。
        "authors": paper.get("authors") or None,
        "arxiv_id": paper.get("arxiv_id"),
    }


class IngestionPersistenceAdapter:
    """Persist an ingestion batch while isolating fail-open secondary stores."""

    def __init__(
        self,
        *,
        documents: DocumentWriter,
        rank_snapshots: RankSnapshotRepository,
        vector_writer_factory: Callable[[], object],
        graph_extractor_factory: Callable[[], object],
        graph_writer_factory: Callable[[], object],
    ) -> None:
        self.documents = documents
        self.rank_snapshots = rank_snapshots
        self.vector_writer_factory = vector_writer_factory
        self.graph_extractor_factory = graph_extractor_factory
        self.graph_writer_factory = graph_writer_factory

    def persist(
        self,
        papers: list[dict],
        *,
        source_label: str,
        snapshot_date: str,
    ) -> int:
        if not papers:
            logger.info("[Pipeline][%s] 无数据，跳过。", source_label)
            return 0

        sorted_papers = sort_papers_for_write(papers)
        vector_documents = project_documents(sorted_papers)

        # 先完成全部文档写入，再按 channel 落地快照：整 channel 替换型走
        # replace_channel_snapshots（删旧切片 + 批量 upsert 单事务原子完成，
        # 避免进程在 delete 后崩溃留下残缺榜单）；累积型 channel 与空 channel
        # 保持逐行 upsert（不删旧切片）。
        channel_writes: dict[str, list[dict]] = {}
        for paper, document in zip(sorted_papers, vector_documents):
            write = project_document_write(paper, document, source_label)
            self.documents.upsert_document(write)
            channel_writes.setdefault(write["source_channel"], []).append(
                {
                    "doc_id": write["id"],
                    "rank_in_period": write["rank_in_period"],
                    "raw_score": float(write["raw_score"] or 0.0),
                    "score": float(write["score"] or 0.0),
                }
            )

        for channel, snapshots in channel_writes.items():
            if channel and channel not in ACCUMULATE_SNAPSHOT_CHANNELS:
                try:
                    self.rank_snapshots.replace_channel_snapshots(
                        snapshot_date, channel, snapshots
                    )
                except Exception as exc:
                    logger.warning(
                        "[Pipeline][%s] 快照整 channel 替换失败 %s/%s: %s",
                        source_label,
                        snapshot_date,
                        channel,
                        exc,
                    )
                continue
            for snapshot in snapshots:
                try:
                    self.rank_snapshots.upsert_rank_snapshot(
                        doc_id=snapshot["doc_id"],
                        snapshot_date=snapshot_date,
                        source_channel=channel,
                        rank_in_period=snapshot["rank_in_period"],
                        raw_score=snapshot["raw_score"],
                        score=snapshot["score"],
                    )
                except Exception as exc:
                    logger.warning(
                        "[Pipeline][%s] 快照写入失败 doc_id=%s: %s",
                        source_label,
                        snapshot["doc_id"],
                        exc,
                    )

        try:
            self.vector_writer_factory().add_documents(
                vector_documents, already_split=False
            )
        except Exception as exc:
            logger.error("[Pipeline][%s] Milvus 写入失败: %s", source_label, exc)

        if source_label.startswith("arxiv"):
            new_documents = [
                document
                for document, paper in zip(vector_documents, sorted_papers)
                if not paper.get("existing_summary_reused", False)
            ]
            if new_documents:
                try:
                    graph_documents = self.graph_extractor_factory().extract(
                        new_documents
                    )
                    graph_writer = self.graph_writer_factory()
                    try:
                        graph_writer.add_graph_documents(graph_documents)
                    finally:
                        graph_writer.close()
                except Exception as exc:
                    logger.error(
                        "[Pipeline][%s] Neo4j 写入失败: %s", source_label, exc
                    )

        logger.info(
            "[Pipeline][%s] 入库完成，%d 条。", source_label, len(sorted_papers)
        )
        return len(sorted_papers)
