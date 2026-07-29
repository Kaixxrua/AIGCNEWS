from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from backend.app.repositories.briefing_repository import BriefingReader
from backend.app.repositories.document_repository import DocumentStatisticsReader
from backend.app.repositories.evaluation_repository import EvaluationSummaryReader
from backend.app.repositories.task_repository import RecentTaskReader

_START_TIME = datetime.now(timezone.utc)


def collect_metrics(
    *,
    task_reader: RecentTaskReader,
    evaluation_reader: EvaluationSummaryReader,
    document_statistics: DocumentStatisticsReader,
    briefing_reader: BriefingReader,
) -> Dict[str, Any]:
    """Collect runtime metrics for the monitor dashboard."""

    uptime_seconds = (datetime.now(timezone.utc) - _START_TIME).total_seconds()

    try:
        task_summary = _task_summary(task_reader)
    except Exception as exc:
        task_summary = {"error": str(exc)}

    try:
        eval_summary = evaluation_reader.get_eval_summary()
    except Exception as exc:
        eval_summary = {"error": str(exc)}

    try:
        doc_count = document_statistics.get_document_count()
    except Exception:
        doc_count = -1

    try:
        briefing_count = len(briefing_reader.list_briefings(limit=1000))
    except Exception:
        briefing_count = -1

    return {
        "uptime_seconds": round(uptime_seconds, 1),
        "document_count": doc_count,
        "briefing_count": briefing_count,
        "tasks": task_summary,
        "rag_evaluation": eval_summary,
    }


def _task_summary(db: RecentTaskReader) -> Dict[str, Any]:
    tasks = db.get_recent_tasks(limit=100)
    total = len(tasks)
    success = sum(1 for task in tasks if task.get("status") == "success")
    failed = sum(1 for task in tasks if task.get("status") == "failed")
    running = sum(1 for task in tasks if task.get("status") == "running")
    last = tasks[0] if tasks else None
    return {
        "total": total,
        "success": success,
        "failed": failed,
        "running": running,
        "last_task": last,
    }
