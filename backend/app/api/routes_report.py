from __future__ import annotations

import asyncio
import json
import logging
import traceback
from datetime import date as _date, datetime as _dt, timedelta as _td
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend.app.core.auth import RequireAdmin, RequireUser
from backend.app.core.config import settings
from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.services.briefing.daily_briefing import DailyBriefingService
from backend.app.services.email_service import EmailService

logger = logging.getLogger(__name__)

router = APIRouter()


_VALID_SOURCES = {"all", "arxiv", "github", "news", "producthunt", "hackernews"}
_VALID_PERIODS = {"daily", "weekly", "monthly"}


class GenerateReportRequest(BaseModel):
    date: Optional[str] = None  # ISO date string, e.g. "2025-03-01"; defaults to today
    source: str = (
        "all"  # "all" | "arxiv" | "github" | "news" | "producthunt" | "hackernews"
    )
    period: str = "daily"  # "daily" | "weekly" | "monthly"
    force_regenerate: bool = True  # 始终重新生成（不走缓存）


# -----------------------------------------------------------------------
# SSE: stream daily briefing generation
# -----------------------------------------------------------------------


async def _briefing_stream(
    target_date: Optional[str],
    source: str = "all",
    period: str = "daily",
    force_regenerate: bool = True,
) -> AsyncGenerator[str, None]:
    try:
        service = DailyBriefingService()
        async for payload in service.stream_generate(
            target_date,
            source=source,
            period=period,
            force_regenerate=force_regenerate,
        ):
            try:
                data = json.dumps(payload, ensure_ascii=False, default=str)
            except Exception:
                data = json.dumps({"type": "error", "data": "serialize_error"})
            yield f"data: {data}\n\n"
    except Exception as exc:
        traceback.print_exc()
        yield f"data: {json.dumps({'type': 'error', 'data': str(exc)})}\n\n"
    finally:
        yield "data: [DONE]\n\n"


@router.post("/report/daily/stream")
async def stream_daily_report(
    request: GenerateReportRequest,
    _: dict = Depends(RequireAdmin),
) -> StreamingResponse:
    """Generate today's (or a specific date's) briefing and stream via SSE.

    source 参数：
      - all         → 综合报告（全源汇总）
      - arxiv       → 学术报告（HF Papers）
      - github      → 工程报告（GitHub Hot）
      - news        → 行业报告（RSS）
      - producthunt → 产品报告（Product Hunt 热榜）
      - hackernews  → 社区报告（Hacker News AI 热帖）

    period 参数：
      - daily   → 日报
      - weekly  → 周报
      - monthly → 月报
    """
    source = request.source if request.source in _VALID_SOURCES else "all"
    period = request.period if request.period in _VALID_PERIODS else "daily"
    return StreamingResponse(
        _briefing_stream(
            request.date,
            source=source,
            period=period,
            force_regenerate=request.force_regenerate,
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


def _resolve_report_date(period: str, date_str: Optional[str]) -> str:
    today = _date.today()
    if date_str:
        try:
            anchor = _dt.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            anchor = today
    else:
        anchor = today

    if period == "weekly":
        # 统一使用周一作为周报 key
        anchor = anchor - _td(days=anchor.weekday())
    elif period == "monthly":
        # 统一使用当月1号作为月报 key
        anchor = anchor.replace(day=1)

    return anchor.isoformat()


@router.get("/report/latest")
async def get_latest_briefing(
    source: str = Query(
        default="all", description="all/arxiv/github/news/producthunt/hackernews"
    ),
    period: str = Query(default="daily", description="daily/weekly/monthly"),
    date: Optional[str] = Query(default=None, description="YYYY-MM-DD，可选"),
):
    """返回指定类型与周期的简报缓存。

    - source: all/arxiv/github/news
    - period: daily/weekly/monthly
    - date: 可选，未传则取今天；weekly 会归一到周一，monthly 会归一到当月1号
    """
    source = source if source in _VALID_SOURCES else "all"
    period = period if period in _VALID_PERIODS else "daily"

    target = _resolve_report_date(period, date)
    # 与 daily_briefing.py 的 cache_date = f"{today}{cache_suffix}_{period}" 保持一致
    suffix = "" if source == "all" else f"_{source}"
    cache_key = f"{target}{suffix}_{period}"

    db = MySQLRepository()
    item = db.get_briefing_by_date(cache_key)
    if item is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "对应简报尚未生成", "cache_key": cache_key},
        )
    return {
        "id": item.get("id"),
        "date": item.get("date"),
        "content": item.get("content", ""),
        "source": source,
        "period": period,
        "cache_key": cache_key,
    }


# -----------------------------------------------------------------------
# REST: briefing history list
# -----------------------------------------------------------------------


@router.get("/report/history")
async def list_briefings(
    limit: int = Query(default=30, ge=1, le=200),
):
    """Return a list of past briefings (id + date + created_at)."""
    db = MySQLRepository()
    items = db.list_briefings(limit=limit)
    return {"items": items, "total": len(items)}


@router.get("/report/{briefing_id}")
async def get_briefing(briefing_id: int):
    """Return the full content of a specific briefing by ID."""
    service = DailyBriefingService()
    item = service.get_briefing(briefing_id)
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
async def eval_summary():
    """Return aggregated RAG evaluation statistics."""
    from backend.app.services.evaluation.rag_metrics import RAGMetricsService

    svc = RAGMetricsService()
    return svc.get_summary()


@router.get("/report/eval/list")
async def eval_list(
    limit: int = Query(default=50, ge=1, le=500),
):
    """Return the most recent RAG evaluation records."""
    from backend.app.services.evaluation.rag_metrics import RAGMetricsService

    svc = RAGMetricsService()
    items = svc.list_evaluations(limit=limit)
    return {"items": items, "total": len(items)}


# -----------------------------------------------------------------------
# Briefing Subscription APIs
# -----------------------------------------------------------------------


def _get_email_service(request: Request) -> EmailService:
    """从 app.state 获取 Redis 并构造 EmailService 实例。"""
    redis_client = getattr(request.app.state, "redis", None)
    return EmailService(
        redis_client=redis_client,
        smtp_host=settings.SMTP_HOST,
        smtp_port=settings.SMTP_PORT,
        smtp_username=settings.SMTP_USERNAME,
        smtp_password=settings.SMTP_PASSWORD,
        smtp_from_email=settings.SMTP_FROM_EMAIL,
        smtp_from_name=settings.SMTP_FROM_NAME,
        smtp_use_tls=settings.SMTP_USE_TLS,
    )


class SubscribeRequest(BaseModel):
    source: str = "all"
    period: str = "daily"


@router.post("/report/subscribe")
async def subscribe_briefing(
    body: SubscribeRequest,
    user: dict = Depends(RequireUser),
):
    """订阅简报邮件推送。用户点击订阅后，当对应简报生成时会发送到注册邮箱。"""
    source = body.source if body.source in _VALID_SOURCES else "all"
    period = body.period if body.period in _VALID_PERIODS else "daily"
    email = user.get("email", "")
    user_id = user.get("user_id")
    if not email:
        return JSONResponse(
            status_code=400,
            content={"detail": "用户邮箱为空，无法订阅"},
        )
    db = MySQLRepository()
    sub = db.upsert_briefing_subscription(
        user_id=user_id, email=email, source=source, period=period
    )
    return {"message": "订阅成功", "subscription": sub}


@router.post("/report/unsubscribe")
async def unsubscribe_briefing(
    body: SubscribeRequest,
    user: dict = Depends(RequireUser),
):
    """取消简报邮件订阅。"""
    source = body.source if body.source in _VALID_SOURCES else "all"
    period = body.period if body.period in _VALID_PERIODS else "daily"
    user_id = user.get("user_id")
    db = MySQLRepository()
    ok = db.cancel_briefing_subscription(user_id=user_id, source=source, period=period)
    if ok:
        return {"message": "已取消订阅"}
    return JSONResponse(
        status_code=404,
        content={"detail": "未找到对应订阅记录"},
    )


@router.get("/report/subscriptions")
async def get_my_subscriptions(
    user: dict = Depends(RequireUser),
):
    """获取当前用户的所有活跃简报订阅。"""
    db = MySQLRepository()
    subs = db.get_user_briefing_subscriptions(user_id=user.get("user_id"))
    return {"items": subs}


@router.post("/report/send-to-email")
async def send_briefing_to_email(
    body: SubscribeRequest,
    request: Request,
    user: dict = Depends(RequireUser),
):
    """将当前简报立即发送到用户邮箱（一次性发送，不需要订阅）。"""
    source = body.source if body.source in _VALID_SOURCES else "all"
    period = body.period if body.period in _VALID_PERIODS else "daily"
    email = user.get("email", "")
    if not email:
        return JSONResponse(
            status_code=400,
            content={"detail": "用户邮箱为空，无法发送"},
        )

    # 获取最新简报
    target = _resolve_report_date(period, None)
    suffix = "" if source == "all" else f"_{source}"
    cache_key = f"{target}{suffix}_{period}"

    db = MySQLRepository()
    item = db.get_briefing_by_date(cache_key)
    if item is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "对应简报尚未生成，无法发送"},
        )

    email_svc = _get_email_service(request)
    await email_svc.send_briefing(
        to_email=email,
        briefing_content=item.get("content", ""),
        source=source,
        period=period,
        date_str=target,
    )
    return {"message": f"简报已发送至 {email}"}
