from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend.app.api.dependencies import (
    get_briefing_repository,
    get_briefing_subscription_repository,
    get_daily_briefing_service,
    get_evaluation_repository,
    get_report_subscription_plan_service,
    get_user_subscription_repository,
)
from backend.app.core.auth import RequireAdmin, RequireUser
from backend.app.core.config import settings
from backend.app.repositories.briefing_repository import (
    BriefingReader,
    BriefingSubscriptionRepository,
)
from backend.app.repositories.evaluation_repository import EvaluationRepository
from backend.app.repositories.user_subscription_repository import (
    UserSubscriptionRepository,
)
from backend.app.services.briefing.daily_briefing import (
    DailyBriefingService,
    get_briefing_cache_key,
    normalize_briefing_locale,
    select_briefing_content,
)
from backend.app.services.email_service import (
    BriefingDeliveryError,
    EmailService,
    build_email_service,
)
from backend.app.services.ingestion.base_crawler import today_cst
from backend.app.services.membership.subscription_quota import (
    SubscriptionQuotaExceededError,
    collect_active_daily_sources,
    ensure_subscription_quota,
)
from backend.app.services.push.errors import (
    PushChannelDisabledError,
    PushChannelNotFoundError,
    PushChannelNotVerifiedError,
    VipRequiredError,
)
from backend.app.services.report.subscription_plan_service import (
    DeliveryTarget,
    InvalidSubscriptionPlanError,
    ReportSubscriptionPlanService,
)

logger = logging.getLogger(__name__)

# SSE 错误帧的通用对外文案：原始异常只进服务端日志，不外泄给客户端。
_STREAM_ERROR_MESSAGE = "服务内部错误，请稍后重试"

router = APIRouter()

# SSE 心跳间隔统一由 settings.sse_heartbeat_interval（SSE_HEARTBEAT_INTERVAL）提供。
_SSE_HEARTBEAT_INTERVAL_SECONDS = float(settings.sse_heartbeat_interval)


_VALID_SOURCES = {"all", "arxiv", "github", "news", "producthunt", "hackernews", "x", "dailyhot"}


def _enforce_subscription_quota(
    user: dict,
    adding_sources: set[str],
    briefing_repository: BriefingSubscriptionRepository,
    user_subscription_repository: UserSubscriptionRepository,
) -> None:
    """免费档订阅档位校验（admin 豁免，与 MCP 配额同一运营口径）。

    跨体系 A（briefing_subscriptions）+ B（user_subscriptions）合计活跃
    日报模块，防止「A 订 1 个 + B 订 8 个」绕过；存量豁免语义由
    ensure_subscription_quota 承载（已活跃 source 重复 upsert 幂等放行）。
    """
    if user.get("role") == "admin":
        return
    active = collect_active_daily_sources(
        briefing_subscriptions=briefing_repository,
        user_subscriptions=user_subscription_repository,
        user_id=user.get("user_id"),
    )
    try:
        ensure_subscription_quota(
            tier=str(user.get("membership_tier") or "free"),
            active_sources=active,
            adding_sources=adding_sources,
        )
    except SubscriptionQuotaExceededError as exc:
        raise HTTPException(status_code=403, detail=exc.detail) from exc


class GenerateReportRequest(BaseModel):
    date: Optional[str] = None  # ISO date string, e.g. "2025-03-01"; defaults to today
    source: str = (
        "all"  # "all" | "arxiv" | "github" | "news" | "producthunt" | "hackernews" | "x" | "dailyhot"
    )
    force_regenerate: bool = True  # 始终重新生成（不走缓存）
    locale: str = "zh-CN"


# -----------------------------------------------------------------------
# SSE: stream daily briefing generation
# -----------------------------------------------------------------------


async def _briefing_stream(
    service: DailyBriefingService,
    target_date: Optional[str],
    source: str = "all",
    force_regenerate: bool = True,
    locale: str = "zh-CN",
) -> AsyncGenerator[str, None]:
    stream: AsyncGenerator[dict, None] | None = None
    next_payload: asyncio.Task | None = None
    try:
        stream = service.stream_generate(
            target_date,
            source=source,
            force_regenerate=force_regenerate,
            locale=locale,
            generate_bilingual=True,
        )

        while True:
            next_payload = asyncio.create_task(stream.__anext__())
            while not next_payload.done():
                done, _ = await asyncio.wait(
                    {next_payload}, timeout=_SSE_HEARTBEAT_INTERVAL_SECONDS
                )
                if not done:
                    yield ": heartbeat\n\n"

            try:
                payload = next_payload.result()
            except StopAsyncIteration:
                break

            try:
                data = json.dumps(payload, ensure_ascii=False, default=str)
            except Exception:
                data = json.dumps({"type": "error", "data": "serialize_error"})
            yield f"data: {data}\n\n"
    except Exception:
        logger.exception("[Report] briefing stream failed")
        yield f"data: {json.dumps({'type': 'error', 'data': _STREAM_ERROR_MESSAGE})}\n\n"
    finally:
        if next_payload is not None and not next_payload.done():
            next_payload.cancel()
        if stream is not None:
            try:
                await stream.aclose()
            except Exception as exc:
                logger.debug("[Report] briefing stream close failed: %s", exc)
        yield "data: [DONE]\n\n"


@router.post("/report/daily/stream")
async def stream_daily_report(
    request: GenerateReportRequest,
    _: dict = Depends(RequireAdmin),
    service: DailyBriefingService = Depends(get_daily_briefing_service),
) -> StreamingResponse:
    """Generate today's (or a specific date's) daily briefing and stream via SSE.

    source 参数：
      - all         → 综合报告（全源汇总）
      - arxiv       → 学术报告（HF Papers）
      - github      → 工程报告（GitHub Hot）
      - news        → 行业报告（RSS）
      - producthunt → 产品报告（Product Hunt 热榜）
      - hackernews  → 社区报告（Hacker News AI 热帖）
      - x           → X 动态报告（关注账号当日动态，按账号组织）
      - dailyhot    → 全网热榜报告（中文站点聚合）

    简报仅按日生成（weekly/monthly 已移除）。
    """
    source = request.source if request.source in _VALID_SOURCES else "all"
    return StreamingResponse(
        _briefing_stream(
            service,
            request.date,
            source=source,
            force_regenerate=request.force_regenerate,
            locale=normalize_briefing_locale(request.locale),
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# -----------------------------------------------------------------------
# REST: GET /report/latest  — 返回今日已生成的日报（缓存命中）
# -----------------------------------------------------------------------


@router.get("/report/latest")
async def get_latest_briefing(
    source: str = Query(
        default="all", description="all/arxiv/github/news/producthunt/hackernews/x/dailyhot"
    ),
    date: Optional[str] = Query(default=None, description="YYYY-MM-DD，可选"),
    locale: str = Query(default="zh-CN", description="zh-CN/en"),
    repository: BriefingReader = Depends(get_briefing_repository),
):
    """返回指定来源的日报缓存。

    - source: all/arxiv/github/news/producthunt/hackernews/x/dailyhot
    - date: 可选，未传则取今天
    """
    source = source if source in _VALID_SOURCES else "all"

    target = date or today_cst()
    cache_key = get_briefing_cache_key(target, source)

    item = repository.get_briefing_by_date(cache_key)
    if item is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "对应简报尚未生成", "cache_key": cache_key},
        )
    return {
        "id": item.get("id"),
        "date": item.get("date"),
        "content": select_briefing_content(item, locale),
        "source": source,
        "cache_key": cache_key,
    }


# -----------------------------------------------------------------------
# REST: briefing history list
# -----------------------------------------------------------------------


@router.get("/report/history")
async def list_briefings(
    limit: int = Query(default=30, ge=1, le=200),
    repository: BriefingReader = Depends(get_briefing_repository),
):
    """Return a list of past briefings (id + date + created_at)."""
    items = repository.list_briefings(limit=limit)
    return {"items": items, "total": len(items)}


# -----------------------------------------------------------------------
# Report subscription plan facade (source × delivery wizard)
# -----------------------------------------------------------------------


class PlanDeliveryRequest(BaseModel):
    kind: str  # account_email | push_channel | rss
    channel_id: int | None = None
    feed: str | None = None


class PlanDeliveryCapability(BaseModel):
    kind: str
    key: str
    channel_id: int | None = None
    channel_type: str | None = None
    target: str | None = None
    verified: bool | None = None
    status: str | None = None
    selectable: bool
    disabled_reason: str | None = None


class SubscriptionPlanResponse(BaseModel):
    can_select_multiple_sources: bool
    max_sources: int
    active_sources: list[str]
    capabilities: list[PlanDeliveryCapability]


class SubscriptionPlanRequest(BaseModel):
    sources: list[str]
    deliveries: list[PlanDeliveryRequest]
    frequency: str = "daily"
    idempotency_key: str | None = None


class PlanAppliedDelivery(BaseModel):
    kind: str
    channel_id: int | None = None
    feed: str | None = None
    status: str


class SubscriptionPlanApplyResponse(BaseModel):
    sources: list[str]
    deliveries: list[PlanAppliedDelivery]
    idempotency_key: str | None = None


def _user_id_or_raise(user: dict) -> int:
    try:
        user_id = int(user.get("user_id") or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="用户身份无效") from exc
    if user_id <= 0:
        raise HTTPException(status_code=401, detail="用户身份无效")
    return user_id


def _map_subscription_plan_error(
    exc: Exception,
) -> HTTPException:
    if isinstance(exc, SubscriptionQuotaExceededError):
        return HTTPException(
            status_code=403,
            detail={"code": "quota-exceeded", "message": exc.detail},
        )
    if isinstance(exc, VipRequiredError):
        return HTTPException(
            status_code=403,
            detail={"code": exc.code, "message": exc.detail},
        )
    if isinstance(exc, (PushChannelNotFoundError,)):
        return HTTPException(status_code=404, detail=exc.detail)
    if isinstance(exc, (PushChannelNotVerifiedError, PushChannelDisabledError)):
        return HTTPException(status_code=400, detail=exc.detail)
    if isinstance(exc, InvalidSubscriptionPlanError):
        return HTTPException(status_code=422, detail=exc.detail)
    if isinstance(exc, HTTPException):
        return exc
    logger.warning("[ReportSubscriptionPlan] apply failed: %s", exc, exc_info=True)
    return HTTPException(status_code=500, detail="订阅计划保存失败，请稍后重试")


@router.get("/report/subscription-plan", response_model=SubscriptionPlanResponse)
async def get_subscription_plan(
    user: dict = Depends(RequireUser),
    service: ReportSubscriptionPlanService = Depends(
        get_report_subscription_plan_service
    ),
):
    """返回当前用户的日报订阅计划能力与活跃状态（不含 RSS token）。"""
    user_id = _user_id_or_raise(user)
    return service.get_plan(user=user, user_id=user_id)


@router.post(
    "/report/subscription-plan",
    response_model=SubscriptionPlanApplyResponse,
)
async def apply_subscription_plan(
    body: SubscriptionPlanRequest,
    user: dict = Depends(RequireUser),
    service: ReportSubscriptionPlanService = Depends(
        get_report_subscription_plan_service
    ),
):
    """一次性提交 source 集合与 delivery 集合，事务内写入 briefing_subscriptions /
    user_subscriptions；RSS 为 virtual delivery，不创建 Push 记录。
    """
    user_id = _user_id_or_raise(user)
    email = user.get("email", "")
    if not email:
        raise HTTPException(status_code=400, detail="用户邮箱为空，无法订阅")

    if body.frequency != "daily":
        raise HTTPException(status_code=422, detail="当前仅支持 daily 频率")

    try:
        result = service.apply_plan(
            user=user,
            user_id=user_id,
            email=email,
            sources=body.sources,
            deliveries=[
                DeliveryTarget(
                    kind=d.kind,
                    channel_id=d.channel_id,
                    feed=d.feed,
                )
                for d in body.deliveries
            ],
            idempotency_key=body.idempotency_key,
        )
    except Exception as exc:
        mapped = _map_subscription_plan_error(exc)
        raise mapped from exc
    return result


@router.get("/report/{briefing_id}")
async def get_briefing(
    briefing_id: int,
    repository: BriefingReader = Depends(get_briefing_repository),
):
    """Return the full content of a specific briefing by ID."""
    item = repository.get_briefing(briefing_id)
    if item is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Briefing {briefing_id} not found"},
        )
    return item


# -----------------------------------------------------------------------
# REST: RAG evaluation results
# -----------------------------------------------------------------------


@router.get("/report/eval/summary")
async def eval_summary(
    _: dict = Depends(RequireAdmin),
    repository: EvaluationRepository = Depends(get_evaluation_repository),
):
    """Return aggregated RAG evaluation statistics.

    管理员口径与 /monitor 一致：内部评估明细不对普通注册用户暴露。
    """
    from backend.app.services.evaluation.rag_metrics import RAGMetricsService

    svc = RAGMetricsService(repository)
    return svc.get_summary()


@router.get("/report/eval/list")
async def eval_list(
    limit: int = Query(default=50, ge=1, le=500),
    _: dict = Depends(RequireAdmin),
    repository: EvaluationRepository = Depends(get_evaluation_repository),
):
    """Return the most recent RAG evaluation records.

    管理员口径与 /monitor 一致：内部评估明细不对普通注册用户暴露。
    """
    from backend.app.services.evaluation.rag_metrics import RAGMetricsService

    svc = RAGMetricsService(repository)
    items = svc.list_evaluations(limit=limit)
    return {"items": items, "total": len(items)}


# -----------------------------------------------------------------------
# Briefing Subscription APIs
# -----------------------------------------------------------------------


def _get_email_service(request: Request) -> EmailService:
    """从 app.state 获取 Redis 并构造 EmailService 实例。"""
    redis_client = getattr(request.app.state, "redis", None)
    return build_email_service(redis_client)


class SubscribeRequest(BaseModel):
    source: str = "all"
    date: Optional[str] = None
    locale: str = "zh-CN"


class BatchSubscribeRequest(BaseModel):
    sources: list[str]
    date: Optional[str] = None


async def _send_cached_briefing_to_email(
    *,
    request: Request,
    repository: BriefingReader,
    email: str,
    source: str,
    date_str: Optional[str],
    locale: str = "zh-CN",
) -> str:
    """发送已生成的简报缓存到指定邮箱，返回实际使用的报告日期。"""
    target = date_str or today_cst()
    cache_key = get_briefing_cache_key(target, source)

    item = repository.get_briefing_by_date(cache_key)
    if item is None:
        raise HTTPException(
            status_code=404,
            detail="对应简报尚未生成，无法发送",
        )

    email_svc = _get_email_service(request)
    try:
        await email_svc.send_briefing(
            to_email=email,
            briefing_content=select_briefing_content(item, locale),
            source=source,
            period="daily",
            date_str=target,
        )
    except BriefingDeliveryError as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from exc
    return target


@router.post("/report/subscribe")
async def subscribe_briefing(
    body: SubscribeRequest,
    user: dict = Depends(RequireUser),
    repository: BriefingSubscriptionRepository = Depends(
        get_briefing_subscription_repository
    ),
    user_subscription_repository: UserSubscriptionRepository = Depends(
        get_user_subscription_repository
    ),
):
    """订阅简报邮件推送；日报生成后会自动推送到注册邮箱。"""
    source = body.source if body.source in _VALID_SOURCES else "all"
    email = user.get("email", "")
    user_id = user.get("user_id")
    if not email:
        return JSONResponse(
            status_code=400,
            content={"detail": "用户邮箱为空，无法订阅"},
        )

    _enforce_subscription_quota(
        user, {source}, repository, user_subscription_repository
    )
    sub = repository.upsert_briefing_subscription(
        user_id=user_id, email=email, source=source
    )
    return {
        "message": f"订阅成功，日报生成后将推送至 {email}",
        "subscription": sub,
    }


@router.post("/report/unsubscribe")
async def unsubscribe_briefing(
    body: SubscribeRequest,
    user: dict = Depends(RequireUser),
    repository: BriefingSubscriptionRepository = Depends(
        get_briefing_subscription_repository
    ),
):
    """取消简报邮件订阅。"""
    source = body.source if body.source in _VALID_SOURCES else "all"
    user_id = user.get("user_id")
    ok = repository.cancel_briefing_subscription(
        user_id=user_id,
        source=source,
    )
    if ok:
        return {"message": "已取消订阅"}
    return JSONResponse(
        status_code=404,
        content={"detail": "未找到对应订阅记录"},
    )


@router.get("/report/subscriptions")
async def get_my_subscriptions(
    user: dict = Depends(RequireUser),
    repository: BriefingSubscriptionRepository = Depends(
        get_briefing_subscription_repository
    ),
):
    """获取当前用户的所有活跃简报订阅。"""
    subs = repository.get_user_briefing_subscriptions(
        user_id=user.get("user_id")
    )
    return {"items": subs}


@router.post("/report/subscriptions/batch")
async def batch_subscribe_briefings(
    body: BatchSubscribeRequest,
    user: dict = Depends(RequireUser),
    repository: BriefingSubscriptionRepository = Depends(
        get_briefing_subscription_repository
    ),
    user_subscription_repository: UserSubscriptionRepository = Depends(
        get_user_subscription_repository
    ),
):
    """批量订阅日报领域；日报生成后会自动推送到注册邮箱。"""
    email = user.get("email", "")
    user_id = user.get("user_id")
    if not email:
        return JSONResponse(
            status_code=400,
            content={"detail": "用户邮箱为空，无法订阅"},
        )

    sources: list[str] = []
    for source in body.sources:
        if source in _VALID_SOURCES and source not in sources:
            sources.append(source)
    if not sources:
        return JSONResponse(
            status_code=400,
            content={"detail": "请选择至少一个有效订阅领域"},
        )

    _enforce_subscription_quota(
        user, set(sources), repository, user_subscription_repository
    )
    subscriptions = [
        repository.upsert_briefing_subscription(
            user_id=user_id,
            email=email,
            source=source,
        )
        for source in sources
    ]
    return {
        "message": f"已订阅 {len(subscriptions)} 个日报领域，日报生成后将推送至 {email}",
        "sources": sources,
        "items": subscriptions,
        "total": len(subscriptions),
    }


@router.post("/report/send-to-email")
async def send_briefing_to_email(
    body: SubscribeRequest,
    request: Request,
    user: dict = Depends(RequireUser),
    repository: BriefingReader = Depends(get_briefing_repository),
):
    """将当前简报立即发送到用户邮箱（一次性发送，不需要订阅）。"""
    source = body.source if body.source in _VALID_SOURCES else "all"
    email = user.get("email", "")
    if not email:
        return JSONResponse(
            status_code=400,
            content={"detail": "用户邮箱为空，无法发送"},
        )

    sent_date = await _send_cached_briefing_to_email(
        request=request,
        repository=repository,
        email=email,
        source=source,
        date_str=body.date,
        locale=body.locale,
    )
    return {"message": f"简报已发送至 {email}", "sent_date": sent_date}


