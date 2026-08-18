from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, Query, Request

from backend.app.api.dependencies import (
    get_briefing_repository,
    get_document_repository,
    get_error_event_repository,
    get_evaluation_repository,
    get_health_check_service,
    get_ingestion_task_repository,
    get_readiness_check,
)
from backend.app.core.auth import RequireAdmin
from backend.app.monitoring.health import HealthCheckService, ReadinessCheck
from backend.app.repositories.briefing_repository import BriefingReader
from backend.app.repositories.document_repository import DocumentStatisticsReader
from backend.app.repositories.error_event_repository import ErrorEventReader
from backend.app.repositories.evaluation_repository import EvaluationSummaryReader
from backend.app.repositories.task_repository import (
    MonitorTaskRepository,
    RecentTaskReader,
)

logger = logging.getLogger(__name__)

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

    # 该端点对匿名可达（编排探活）：内部异常类名等细节只进服务端日志，
    # 对外只回 not_ready；管理员的明细口径走 /monitor/health 与 ops 诊断。
    logger.warning("[Monitor] readiness check failed: %s", result)
    raise HTTPException(
        status_code=503,
        detail={"status": "not_ready", "runtime_ready": False},
    )


@router.get("/monitor/health")
async def health_check(
    _: dict = Depends(RequireAdmin),
    service: HealthCheckService = Depends(get_health_check_service),
):
    """Full health check across PostgreSQL and supporting services.

    管理员口径与 /monitor/tasks 一致：内部服务明细不对普通注册用户暴露。
    """
    return await asyncio.to_thread(service.run)


@router.get("/monitor/metrics")
async def system_metrics(
    request: Request,
    _: dict = Depends(RequireAdmin),
    evaluation_reader: EvaluationSummaryReader = Depends(get_evaluation_repository),
    task_reader: RecentTaskReader = Depends(get_ingestion_task_repository),
    document_statistics: DocumentStatisticsReader = Depends(get_document_repository),
    briefing_reader: BriefingReader = Depends(get_briefing_repository),
):
    """Collect runtime metrics: uptime, document count, task stats, eval summary.

    管理员口径与 /monitor/tasks 一致：运行指标不对普通注册用户暴露。
    MCP 调用计数优先取 Redis 聚合快照（app.state 服务，异步），
    再在 worker 线程里跑其余同步采集。
    """
    from backend.app.monitoring.mcp_redis_metrics import resolve_tool_call_metrics
    from backend.app.monitoring.metrics import collect_metrics

    mcp_snapshot = await resolve_tool_call_metrics(request).snapshot()
    result = await asyncio.to_thread(
        collect_metrics,
        task_reader=task_reader,
        evaluation_reader=evaluation_reader,
        document_statistics=document_statistics,
        briefing_reader=briefing_reader,
        mcp_tool_calls_snapshot=mcp_snapshot,
    )
    return result


@router.get("/monitor/tasks")
async def recent_tasks(
    page: int = 1,
    page_size: int = Query(default=10, ge=1, le=100),
    _: dict = Depends(RequireAdmin),
    db: MonitorTaskRepository = Depends(get_ingestion_task_repository),
):
    """Return paginated ingestion task records."""
    result = await asyncio.to_thread(db.list_tasks, page, page_size)
    return result


@router.get("/monitor/errors")
async def recent_error_events(
    page: int = 1,
    page_size: int = Query(default=10, ge=1, le=100),
    _: dict = Depends(RequireAdmin),
    db: ErrorEventReader = Depends(get_error_event_repository),
):
    """Return paginated backend error events (newest first).

    管理员口径与 /monitor/tasks 一致：错误事件含 logger 名与异常堆栈，
    不对普通注册用户暴露。
    """
    result = await asyncio.to_thread(db.list_events, page, page_size)
    return result
