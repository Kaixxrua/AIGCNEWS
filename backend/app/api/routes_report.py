from __future__ import annotations

import json
import traceback
from datetime import date as _date, datetime as _dt, timedelta as _td
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from backend.app.core.auth import RequireAdmin
from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.services.briefing.daily_briefing import DailyBriefingService

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
