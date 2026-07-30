from __future__ import annotations

"""Administrative ingestion command adapters."""

import logging

logger = logging.getLogger(__name__)
VALID_SOURCES = frozenset({"arxiv", "github", "news", "producthunt", "hackernews"})


class IngestionAdminService:
    """Expose ingestion entry points as background-task compatible commands."""

    def smart_ingest(self, limit: int) -> None:
        from backend.app.services.ingestion.pipeline import run_smart_ingestion

        run_smart_ingestion(limit=limit)

    def force_ingest(self, limit: int) -> None:
        from backend.app.services.ingestion.pipeline import run_ingestion_pipeline

        run_ingestion_pipeline(limit=limit)

    def ingest_by_date(self, target_date: str, limit: int) -> None:
        from backend.app.services.ingestion.pipeline import run_ingestion_pipeline

        logger.info("[Ops] 开始按日期采集：target_date=%s, limit=%d", target_date, limit)
        try:
            result = run_ingestion_pipeline(limit=limit, target_date=target_date)
            ingested = result.get("ingested_total", 0) if isinstance(result, dict) else 0
            logger.info("[Ops] 按日期采集完成：date=%s, ingested=%d", target_date, ingested)
        except Exception:
            logger.exception("[Ops] 按日期采集失败：date=%s", target_date)

    def ingest_source(self, source_name: str, limit: int) -> None:
        from backend.app.services.ingestion.pipeline import run_single_source_pipeline

        run_single_source_pipeline(source_name=source_name, limit=limit)
