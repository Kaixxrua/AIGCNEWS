from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from backend.app.repositories.mysql_repo import MySQLRepository

_START_TIME = datetime.now(timezone.utc)


def collect_metrics() -> Dict[str, Any]:
    """Collect runtime metrics for the monitor dashboard."""
    db = MySQLRepository()

    uptime_seconds = (datetime.now(timezone.utc) - _START_TIME).total_seconds()

    try:
        task_summary = _task_summary(db)
    except Exception as exc:
        task_summary = {"error": str(exc)}

    try:
        eval_summary = db.get_eval_summary()
    except Exception as exc:
        eval_summary = {"error": str(exc)}

    try:
        doc_count = db.get_document_count()
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
    }


def _task_summary(db: MySQLRepository) -> Dict[str, Any]:
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
