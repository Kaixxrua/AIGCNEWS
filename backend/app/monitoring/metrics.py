from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from backend.app.repositories.document_repository import DocumentStatisticsReader
from backend.app.repositories.evaluation_repository import EvaluationSummaryReader
from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.services.project_catalog_shadow import project_catalog_shadow_snapshot
from backend.app.repositories.task_repository import (
    MonitorMetricsRepository,
    RecentTaskReader,
)

_START_TIME = datetime.now(timezone.utc)


def collect_metrics(
    repository: MonitorMetricsRepository | None = None,
    task_reader: RecentTaskReader | None = None,
    evaluation_reader: EvaluationSummaryReader | None = None,
    document_statistics: DocumentStatisticsReader | None = None,
) -> Dict[str, Any]:
    """Collect runtime metrics for the monitor dashboard."""
    db = repository if repository is not None else MySQLRepository()
    documents = document_statistics or _default_document_statistics(db)
    tasks = task_reader if task_reader is not None else _default_task_reader(db)
    evaluations = (
        evaluation_reader
        if evaluation_reader is not None
        else _default_evaluation_reader(db)
    )

    uptime_seconds = (datetime.now(timezone.utc) - _START_TIME).total_seconds()

    try:
        task_summary = _task_summary(tasks)
    except Exception as exc:
        task_summary = {"error": str(exc)}

    try:
        eval_summary = evaluations.get_eval_summary()
    except Exception as exc:
        eval_summary = {"error": str(exc)}

    try:
        doc_count = documents.get_document_count()
    except Exception as exc:
        doc_count = -1

    try:
        briefing_count = len(db.list_briefings(limit=1000))
    except Exception as exc:
        briefing_count = -1

    return {
        "uptime_seconds": round(uptime_seconds, 1),
        "document_count": doc_count,
        "briefing_count": briefing_count,
        "tasks": task_summary,
        "rag_evaluation": eval_summary,
        "project_catalog_shadow": project_catalog_shadow_snapshot(),
    }


def _default_document_statistics(
    repository: MonitorMetricsRepository,
) -> DocumentStatisticsReader:
    component = getattr(repository, "documents", None)
    return component if component is not None else repository  # type: ignore[return-value]


def _default_task_reader(repository: MonitorMetricsRepository) -> RecentTaskReader:
    component = getattr(repository, "ingestion_tasks", None)
    return component if component is not None else repository  # type: ignore[return-value]


def _default_evaluation_reader(
    repository: MonitorMetricsRepository,
) -> EvaluationSummaryReader:
    component = getattr(repository, "evaluations", None)
    return component if component is not None else repository  # type: ignore[return-value]


def _task_summary(db: RecentTaskReader) -> Dict[str, Any]:
    tasks = db.get_recent_tasks(limit=100)
    total = len(tasks)
    success = sum(1 for t in tasks if t.get("status") == "success")
    failed = sum(1 for t in tasks if t.get("status") == "failed")
    running = sum(1 for t in tasks if t.get("status") == "running")
    last = tasks[0] if tasks else None
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "running": running,
        "last_task": last,
    }
