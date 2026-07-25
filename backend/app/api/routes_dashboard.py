from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi_cache.decorator import cache

from backend.app.api.dependencies import (
    get_document_repository,
    get_rank_snapshot_repository,
    get_user_account_repository,
)
from backend.app.repositories.document_repository import DocumentStatisticsReader
from backend.app.repositories.rank_snapshot_repository import RankSnapshotReader
from backend.app.repositories.user_account_repository import UserStatisticsReader
from backend.app.services.dashboard import policy
from backend.app.services.dashboard.query_service import DashboardQueryService

router = APIRouter()


def _dashboard_cache_key_builder(
    func,
    namespace: str = "",
    request: Request | None = None,
    response: Response | None = None,
    *args,
    **kwargs,
) -> str:
    """为 dashboard 接口构建稳定 cache key，确保 date/period/source/limit 等参数隔离。

    关键修复：当 date 参数未传入时，显式注入 CST 当天日期到 key 中，
    防止跨日后命中前一天缓存（原先无 date 参数时 key 完全相同）。
    """
    from datetime import datetime, timezone, timedelta

    query_params = dict(request.query_params) if request is not None else {}

    # 若未传 date 参数，注入今日 CST 日期，确保每天 key 不同
    if "date" not in query_params:
        tz_cst = timezone(timedelta(hours=8))
        query_params["_date_injected"] = datetime.now(tz_cst).strftime("%Y-%m-%d")

    payload = {
        "path": request.url.path if request is not None else func.__name__,
        "namespace": namespace,
        "query": query_params,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    digest = hashlib.md5(raw.encode("utf-8")).hexdigest()
    return f"{namespace}:{func.__name__}:{digest}"


# Compatibility exports consumed by routes_mcp and older callers.
def _compute_board_status(snapshot_date_str: str) -> dict:
    return policy.compute_board_status(snapshot_date_str)


def _dedupe_docs(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return policy.dedupe_docs(docs)


def _enrich_doc_pdf_url(doc: Dict[str, Any], request: Request) -> Dict[str, Any]:
    return policy.enrich_doc_pdf_url(doc, request)


def _get_docs_for_date(
    db: RankSnapshotReader,
    date_str: str,
    period: str,
    source_type: Optional[str] = None,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    return DashboardQueryService(db).get_docs_for_date(
        date_str, period, source_type, limit
    )


def _resolve_snapshot_date(date_param: Optional[str]) -> str:
    return policy.resolve_snapshot_date(date_param)


def _score_categories(docs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return policy.score_categories(docs)


@router.get("/dashboard/top")
@cache(expire=3600, namespace="dashboard", key_builder=_dashboard_cache_key_builder)
async def get_top_list(
    request: Request,
    limit: int = Query(default=10, ge=1, le=50),
    source: Optional[str] = Query(
        default=None, description="过滤来源：all/arxiv/github/news"
    ),
    period: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    date: Optional[str] = Query(
        default=None, description="快照日期 YYYY-MM-DD，不传默认今天"
    ),
    rank_snapshots: RankSnapshotReader = Depends(get_rank_snapshot_repository),
):
    """Return top-N documents ranked by vote count, optionally filtered by source, period and date."""
    source_type = None if (not source or source == "all") else source
    snapshot_date = policy.resolve_snapshot_date(date)

    board = policy.compute_board_status(snapshot_date)

    # 静默期拦截：直接返回空列表，防止前端泄露未解禁数据
    if board["is_embargoed"]:
        return {
            "items": [],
            "total": 0,
            "period": period,
            "snapshot_date": snapshot_date,
            "is_finalized": board["is_finalized"],
            "is_embargoed": True,
        }

    query_service = DashboardQueryService(rank_snapshots)
    docs = await asyncio.to_thread(
        query_service.get_docs_for_date, snapshot_date, period, source_type, 500
    )
    deduped = policy.dedupe_docs(docs)
    top_items = deduped[:limit]

    # 模块四-1：为每条文档注入完整 pdf_media_url
    top_items = [policy.enrich_doc_pdf_url(dict(doc), request) for doc in top_items]

    return {
        "items": top_items,
        "total": len(top_items),
        "period": period,
        "snapshot_date": snapshot_date,
        "is_finalized": board["is_finalized"],
        "is_embargoed": False,
    }


@router.get("/dashboard/radar")
@cache(expire=3600, namespace="dashboard", key_builder=_dashboard_cache_key_builder)
async def get_trend_radar(
    limit: int = Query(default=50, ge=10, le=200),
    source: Optional[str] = Query(
        default=None, description="过滤来源：all/arxiv/github/news"
    ),
    period: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    date: Optional[str] = Query(
        default=None, description="快照日期 YYYY-MM-DD，不传默认今天"
    ),
    rank_snapshots: RankSnapshotReader = Depends(get_rank_snapshot_repository),
):
    """Return trend radar chart data computed from filtered top documents."""
    source_type = None if (not source or source == "all") else source
    snapshot_date = policy.resolve_snapshot_date(date)

    board = policy.compute_board_status(snapshot_date)

    # 静默期拦截
    if board["is_embargoed"]:
        return {
            "radar": [],
            "doc_count": 0,
            "period": period,
            "snapshot_date": snapshot_date,
            "is_finalized": board["is_finalized"],
            "is_embargoed": True,
        }

    query_service = DashboardQueryService(rank_snapshots)
    docs = await asyncio.to_thread(
        query_service.get_docs_for_date,
        snapshot_date,
        period,
        source_type,
        max(limit, 100),
    )
    radar = policy.score_categories(docs[:limit])
    return {
        "radar": radar,
        "doc_count": len(docs[:limit]),
        "period": period,
        "snapshot_date": snapshot_date,
        "is_finalized": board["is_finalized"],
        "is_embargoed": False,
    }


@router.get("/dashboard/summary")
@cache(expire=3600, namespace="dashboard", key_builder=_dashboard_cache_key_builder)
async def get_dashboard_summary(
    request: Request,
    period: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    date: Optional[str] = Query(
        default=None, description="快照日期 YYYY-MM-DD，不传默认今天"
    ),
    user_statistics: UserStatisticsReader = Depends(get_user_account_repository),
    document_statistics: DocumentStatisticsReader = Depends(get_document_repository),
    rank_snapshots: RankSnapshotReader = Depends(get_rank_snapshot_repository),
):
    """Return a combined dashboard payload: period top-10 + radar + basic stats + source breakdown.

    当传入 date 参数时，从 document_rank_snapshots 表查询该日期的历史排行数据；
    未传入时默认查当天，若无快照则回退到原有 documents 表逻辑。
    """
    from datetime import timedelta, timezone as _tz

    snapshot_date = policy.resolve_snapshot_date(date)

    board = policy.compute_board_status(snapshot_date)

    # ── 今日独立访客数（Redis SET：visitor:{YYYY-MM-DD}）──────────
    async def _get_today_unique_visitors() -> int:
        redis_client = getattr(request.app.state, "redis", None)
        if redis_client is None:
            return 0
        tz_cst = _tz(timedelta(hours=8))
        from datetime import datetime as _dt

        today_key = f"visitor:{_dt.now(tz_cst).strftime('%Y-%m-%d')}"
        try:
            count = await redis_client.scard(today_key)
            return int(count or 0)
        except Exception:
            return 0

    # 静默期拦截：返回空排行数据，但统计卡片仍显示全库累计数量
    if board["is_embargoed"]:
        source_counts_embargo = await asyncio.to_thread(document_statistics.get_source_counts)
        total_embargo = sum(source_counts_embargo.values())
        registered_users = await asyncio.to_thread(user_statistics.get_user_count)
        today_registered_users = await asyncio.to_thread(
            user_statistics.get_today_registered_user_count
        )
        user_count = registered_users + today_registered_users
        return {
            "top_list": [],
            "radar": [],
            "stats": {
                "total_documents": total_embargo,
                "source_counts": source_counts_embargo,
                "registered_users": registered_users,
                "today_registered_users": today_registered_users,
                "user_count": user_count,
                "today_unique_visitors": user_count,
            },
            "period": period,
            "snapshot_date": snapshot_date,
            "is_finalized": board["is_finalized"],
            "is_embargoed": True,
        }

    query_service = DashboardQueryService(rank_snapshots)
    docs = await asyncio.to_thread(
        query_service.get_docs_for_date, snapshot_date, period, None, 500
    )
    deduped = policy.dedupe_docs(docs)
    top10 = deduped[:10]
    radar = policy.score_categories(deduped[:50])

    # ── 统计卡片数据 ──────────────────────────────────────────────
    # 始终使用全库累计统计，数字不随日期切换而变化，
    # 展示的是每个来源在数据库中的实际入库总量。
    source_counts = await asyncio.to_thread(document_statistics.get_source_counts)
    total_documents = sum(source_counts.values())
    registered_users = await asyncio.to_thread(user_statistics.get_user_count)
    today_registered_users = await asyncio.to_thread(user_statistics.get_today_registered_user_count)
    user_count = registered_users + today_registered_users
    today_new_documents = await asyncio.to_thread(document_statistics.get_today_document_count)

    return {
        "top_list": top10,
        "radar": radar,
        "stats": {
            "total_documents": total_documents,
            "source_counts": source_counts,
            "registered_users": registered_users,
            "today_registered_users": today_registered_users,
            "user_count": user_count,
            "today_new_documents": today_new_documents,
            "today_unique_visitors": user_count,
        },
        "period": period,
        "snapshot_date": snapshot_date,
        "is_finalized": board["is_finalized"],
        "is_embargoed": False,
    }


@router.get("/dashboard/snapshot-dates")
@cache(expire=60, namespace="dashboard", key_builder=_dashboard_cache_key_builder)
async def get_snapshot_dates(
    limit: int = Query(default=60, ge=1, le=365),
    source: Optional[str] = Query(default=None),
    period: Optional[str] = Query(default=None, pattern="^(daily|weekly|monthly)$"),
    rank_snapshots: RankSnapshotReader = Depends(get_rank_snapshot_repository),
):
    """返回指定来源和周期有快照记录的日期列表（降序）。"""
    source_type = None if (not source or source == "all") else source
    dates = await asyncio.to_thread(
        rank_snapshots.get_snapshot_dates,
        limit,
        source_type,
        period,
    )
    return {
        "dates": dates,
        "total": len(dates),
        "source": source_type or "all",
        "period": period,
    }


@router.get("/dashboard/visitor-count")
async def get_visitor_count(
    request: Request,
    user_statistics: UserStatisticsReader = Depends(get_user_account_repository),
):
    """返回用户数指标（不缓存，实时读取数据库）。"""
    registered_users = await asyncio.to_thread(user_statistics.get_user_count)
    today_registered_users = await asyncio.to_thread(user_statistics.get_today_registered_user_count)
    user_count = registered_users + today_registered_users
    return {
        "user_count": user_count,
        "registered_users": registered_users,
        "today_registered_users": today_registered_users,
        "today_unique_visitors": user_count,
    }


@router.get("/dashboard/github-hot")
@cache(expire=3600, namespace="dashboard", key_builder=_dashboard_cache_key_builder)
async def get_github_hot_list(
    period: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    limit: int = Query(default=10, ge=1, le=50),
):
    """Return GitHub hot repositories ranked by growth + baseline + age correction."""
    from backend.app.services.ingestion.github_hot_service import get_github_hot_rank

    result = await asyncio.to_thread(get_github_hot_rank, period, limit)
    return result
