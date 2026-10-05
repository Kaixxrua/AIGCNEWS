from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request

from backend.app.api.dependencies import (
    get_briefing_repository,
    get_document_repository,
    get_error_event_repository,
    get_evaluation_repository,
    get_health_check_service,
    get_ingestion_task_repository,
    get_payment_order_repository,
    get_readiness_check,
    get_user_account_repository,
)
from backend.app.api.routes_dashboard import cst_today, get_site_visit_repository
from backend.app.core.auth import RequireAdmin
from backend.app.monitoring.health import HealthCheckService, ReadinessCheck
from backend.app.monitoring.mcp_daily_usage import read_mcp_daily_usage_safely
from backend.app.repositories.briefing_repository import BriefingReader
from backend.app.repositories.document_repository import DocumentStatisticsReader
from backend.app.repositories.error_event_repository import ErrorEventReader
from backend.app.repositories.evaluation_repository import EvaluationSummaryReader
from backend.app.repositories.payment_order_repository import PaymentRevenueReader
from backend.app.repositories.site_visit_repository import SiteVisitPlatformReader
from backend.app.repositories.task_repository import (
    MonitorTaskRepository,
    RecentTaskReader,
)
from backend.app.repositories.user_account_repository import UserStatisticsReader
from backend.app.services.dashboard.visit_platforms import (
    build_platform_breakdown_response,
    window_start_date,
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


@router.get("/monitor/mcp-usage")
async def mcp_daily_usage(
    request: Request,
    days: int = Query(default=14, ge=1, le=31),
    _: dict = Depends(RequireAdmin),
):
    """MCP 每日用量汇总：含今天在内最近 days 天（北京时间计日）。

    管理员口径与 /monitor/tasks 一致。数据由 Go MCP 服务写入 mcpusage:*，
    按匿名/免费/会员给出去重客户端、连接（initialize）、工具调用与 429 次数；
    不含管理员与压测流量，匿名按 IP 摘要去重、原始 IP 不入库。
    Redis 未接线或读取失败时返回 available=false 的零值结构。
    """
    redis = getattr(request.app.state, "redis", None)
    return await read_mcp_daily_usage_safely(redis, end_date=cst_today(), days=days)


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


@router.get("/monitor/visit-platforms")
async def visit_platform_breakdown(
    window: str = Query(default="7d", pattern="^(today|7d|30d|all)$"),
    _: dict = Depends(RequireAdmin),
    visits: SiteVisitPlatformReader = Depends(get_site_visit_repository),
):
    """站点访问的平台分布（beacon 按 User-Agent 归类，纯次数口径）。

    管理员口径与 /monitor/tasks 一致。平台计数自 0054 迁移上线日起算，
    更早的访问没有平台维度，all 窗口合计小于站点总访问量是预期。
    爬虫、无头浏览器等自动化访问不计入 total_visits，单列为 automated_visits。
    Depends 键复用 routes_dashboard.get_site_visit_repository 同一函数对象，
    契约测试用 dependency_overrides 替换时对两个路由同时生效。
    """
    today = cst_today()
    rows = await asyncio.to_thread(
        visits.get_platform_breakdown, window_start_date(window, today)
    )
    return build_platform_breakdown_response(rows, window, today)


@router.get("/monitor/user-stats")
async def user_stats(
    _: dict = Depends(RequireAdmin),
    users: UserStatisticsReader = Depends(get_user_account_repository),
):
    """注册用户数与生效 VIP 数（member 档且未到期，口径同 resolve_effective_tier）。

    管理员口径与 /monitor/tasks 一致。Depends 键复用
    dependencies.get_user_account_repository 同一函数对象，
    契约测试用 dependency_overrides 替换时对全部消费路由同时生效。
    """
    total_users = await asyncio.to_thread(users.get_user_count)
    member_users = await asyncio.to_thread(users.get_effective_member_count)
    return {"total_users": total_users, "member_users": member_users}


@router.get("/monitor/revenue-stats")
async def revenue_stats(
    _: dict = Depends(RequireAdmin),
    revenue: PaymentRevenueReader = Depends(get_payment_order_repository),
):
    """Return CNY/USD paid revenue for CST day, week, month, and year."""
    tz_cst = timezone(timedelta(hours=8))
    now = datetime.now(tz_cst)
    today = now.date()
    day_start = datetime.combine(today, datetime.min.time(), tzinfo=tz_cst)
    week_start = day_start - timedelta(days=day_start.weekday())
    month_start = day_start.replace(day=1)
    year_start = day_start.replace(month=1, day=1)
    tomorrow = day_start + timedelta(days=1)
    windows = {
        "today": (day_start, tomorrow),
        "week": (week_start, tomorrow),
        "month": (month_start, tomorrow),
        "year": (year_start, tomorrow),
    }
    return await asyncio.to_thread(revenue.get_revenue_stats, windows=windows)
