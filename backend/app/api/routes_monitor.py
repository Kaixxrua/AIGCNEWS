from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from backend.app.api.dependencies import get_ingestion_task_repository
from backend.app.core.auth import RequireAdmin, RequireUser
from backend.app.repositories.task_repository import MonitorTaskRepository

router = APIRouter()


@router.get("/monitor/health")
async def health_check(_: dict = Depends(RequireUser)):
    """Full health check across all services (Milvus, Neo4j, Ollama, SQLite)."""
    from backend.app.monitoring.health import run_health_checks

    result = await asyncio.to_thread(run_health_checks)
    return result


@router.get("/monitor/metrics")
async def system_metrics(_: dict = Depends(RequireUser)):
    """Collect runtime metrics: uptime, document count, task stats, eval summary."""
    from backend.app.monitoring.metrics import collect_metrics

    result = await asyncio.to_thread(collect_metrics)
    return result


@router.get("/monitor/tasks")
async def recent_tasks(
    page: int = 1,
    page_size: int = 10,
    _: dict = Depends(RequireAdmin),
    db: MonitorTaskRepository = Depends(get_ingestion_task_repository),
):
    """Return paginated ingestion task records."""
    result = await asyncio.to_thread(db.list_tasks, page, page_size)
    return result
