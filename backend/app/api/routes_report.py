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
)
from backend.app.core.auth import RequireAdmin, RequireUser
from backend.app.core.config import settings
from backend.app.repositories.briefing_repository import (
    BriefingReader,
    BriefingSubscriptionRepository,
)
from backend.app.repositories.evaluation_repository import EvaluationRepository
from backend.app.services.briefing.daily_briefing import (
    DailyBriefingService,
    normalize_briefing_locale,
    select_briefing_content,
)
from backend.app.services.email_service import (
    BriefingDeliveryError,
    EmailService,
    build_email_service,
)
from backend.app.services.ingestion.base_crawler import today_cst

logger = logging.getLogger(__name__)

# SSE 错误帧的通用对外文案：原始异常只进服务端日志，不外泄给客户端。
_STREAM_ERROR_MESSAGE = "服务内部错误，请稍后重试"

router = APIRouter()

# SSE 心跳间隔统一由 settings.sse_heartbeat_interval（SSE_HEARTBEAT_INTERVAL）提供。
_SSE_HEARTBEAT_INTERVAL_SECONDS = float(settings.sse_heartbeat_interval)


_VALID_SOURCES = {"all", "arxiv", "github", "news", "producthunt", "hackernews", "x", "dailyhot"}


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
      - x           → X 动态报告（关注账号推文）
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
    # 与 daily_briefing.py 的 cache_date = f"{today}{cache_suffix}" 保持一致
    # （CST 口径；服务器本地时区在 0 点后可能与缓存日期错开一天）
    suffix = "" if source == "all" else f"_{source}"
    cache_key = f"{target}{suffix}"

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
    suffix = "" if source == "all" else f"_{source}"
    cache_key = f"{target}{suffix}"

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
