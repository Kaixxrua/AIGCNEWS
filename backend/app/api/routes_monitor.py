from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends

from backend.app.api.dependencies import (
    get_briefing_repository,
    get_document_repository,
    get_evaluation_repository,
    get_health_check_service,
    get_ingestion_task_repository,
    get_readiness_check,
)
from backend.app.core.auth import RequireAdmin, RequireUser
from backend.app.monitoring.health import HealthCheckService, ReadinessCheck
from backend.app.repositories.briefing_repository import BriefingReader
from backend.app.repositories.document_repository import DocumentStatisticsReader
from backend.app.repositories.evaluation_repository import EvaluationSummaryReader
from backend.app.repositories.task_repository import (
    MonitorTaskRepository,
    RecentTaskReader,
)

router = APIRouter()


@router.get("/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness(
    check: ReadinessCheck = Depends(get_readiness_check),
) -> dict[str, object]:
    result = await asyncio.to_thread(check)
    if result.get("runtime_ready"):
        return result
    from fastapi import HTTPException

    raise HTTPException(status_code=503, detail=result)


@router.get("/monitor/health")
async def health_check(
    _: dict = Depends(RequireUser),
    service: HealthCheckService = Depends(get_health_check_service),
):
    """Full health check across PostgreSQL and supporting services."""
    return await asyncio.to_thread(service.run)


@router.get("/monitor/metrics")
async def system_metrics(
    _: dict = Depends(RequireUser),
    evaluation_reader: EvaluationSummaryReader = Depends(get_evaluation_repository),
    task_reader: RecentTaskReader = Depends(get_ingestion_task_repository),
    document_statistics: DocumentStatisticsReader = Depends(get_document_repository),
    briefing_reader: BriefingReader = Depends(get_briefing_repository),
):
    """Collect runtime metrics: uptime, document count, task stats, eval summary."""
    from backend.app.monitoring.metrics import collect_metrics

    result = await asyncio.to_thread(
        collect_metrics,
        task_reader=task_reader,
        evaluation_reader=evaluation_reader,
        document_statistics=document_statistics,
        briefing_reader=briefing_reader,
    )
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
