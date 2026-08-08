from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi_cache.decorator import cache

from backend.app.api.dependencies import (
    get_application_repositories,
    get_document_repository,
    get_project_catalog_query_service,
    get_rank_snapshot_repository,
    get_user_account_repository,
)
from backend.app.repositories.application_repository_factory import (
    ApplicationRepositories,
)
from backend.app.repositories.document_repository import (
    DocumentRecentReader,
    DocumentStatisticsReader,
)
from backend.app.repositories.rank_snapshot_repository import RankSnapshotReader
from backend.app.repositories.user_account_repository import UserStatisticsReader
from backend.app.services.dashboard import policy
from backend.app.services.dashboard.query_service import DashboardQueryService
from backend.app.services.project_catalog.query_service import ProjectCatalogQueryService

router = APIRouter()

logger = logging.getLogger(__name__)


async def _github_library_count(catalog: ProjectCatalogQueryService) -> Optional[int]:
    """项目库 GitHub 收录总量（与 /projects 列表同一查询口径）。

    documents 表里的 github 行只是 trending 快照流水，数量远小于
    用户实际可浏览的项目库；统计卡片应展示项目库收录量。
    查询失败时返回 None，由调用方回退到 documents 表计数。
    """
    try:
        return await catalog.github_library_total()
    except Exception:
        # 静默降级会掩盖项目库故障：保留回退行为，但留下可检索的告警日志
        logger.warning(
            "[Dashboard] 项目库 GitHub 收录量查询失败，回退到 documents 表计数",
            exc_info=True,
        )
        return None


async def _get_source_counts(
    document_statistics: DocumentStatisticsReader,
    catalog: ProjectCatalogQueryService,
) -> dict[str, int]:
    source_counts = await asyncio.to_thread(document_statistics.get_source_counts)
    github_library_count = await _github_library_count(catalog)
    if github_library_count is not None:
        source_counts = {**source_counts, "github": github_library_count}
    return source_counts


async def _get_mcp_total_calls() -> int:
    """MCP 工具调用累计次数（公开营销位口径；计数器不可用时静默为 0）。"""

    def _query() -> int:
        from backend.app.monitoring.mcp_tools import MCP_TOOL_CALL_METRICS

        return int(MCP_TOOL_CALL_METRICS.snapshot().get("total_calls", 0))

    try:
        return await asyncio.to_thread(_query)
    except Exception:
        return 0


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
    from datetime import datetime, timedelta, timezone

    query_params = dict(request.query_params) if request is not None else {}

    # 前端 cache-buster（_t=Date.now()）只用于穿透浏览器/中间层缓存，
    # 不进服务端 key——否则每请求一个新 key，服务端缓存永远零命中。
    query_params.pop("_t", None)

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
    limit: int = Query(default=10, ge=1, le=500),
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


def _published_at_since(value: Any, cutoff: datetime) -> bool:
    """published_at ISO 串解析后 >= cutoff；空值/无法解析一律剔除。"""
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed >= cutoff


@router.get("/dashboard/x/recent")
@cache(expire=120, namespace="dashboard", key_builder=_dashboard_cache_key_builder)
async def get_x_recent(
    hours: int = Query(default=24, ge=1, le=72),
    limit: int = Query(default=500, ge=1, le=500),
    documents: DocumentRecentReader = Depends(get_document_repository),
):
    """滚动最近 N 小时（默认 24）发布的 X 推文，按发布时间新到旧。

    不走快照/定稿/静默期语义：X 看板默认视图随访问时间滑动，用户时区
    由前端展示层换算。挂 120s 短缓存聚合重复访问（公网隧道单次往返
    ~2s）；key 不含前端 _t 破缓存参数。行为变化：数据最多旧 2 分钟
    （采集 5 分钟一轮，滞后有界）。
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff_iso = cutoff.isoformat()
    docs = await asyncio.to_thread(
        lambda: documents.list_recent_by_source("x", since_iso=cutoff_iso, limit=limit)
    )
    items = [doc for doc in docs if _published_at_since(doc.get("published_at"), cutoff)]
    return {
        "items": items,
        "total": len(items),
        "period": "daily",
        "window_hours": hours,
        "snapshot_date": None,
        "is_finalized": False,
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
    catalog: ProjectCatalogQueryService = Depends(get_project_catalog_query_service),
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
        source_counts_embargo = await _get_source_counts(document_statistics, catalog)
        total_embargo = sum(source_counts_embargo.values())
        registered_users = await asyncio.to_thread(user_statistics.get_user_count)
        today_registered_users = await asyncio.to_thread(
            user_statistics.get_today_registered_user_count
        )
        user_count = registered_users + today_registered_users
        mcp_total_calls = await _get_mcp_total_calls()
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
                "mcp_total_calls": mcp_total_calls,
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
    source_counts = await _get_source_counts(document_statistics, catalog)
    total_documents = sum(source_counts.values())
    registered_users = await asyncio.to_thread(user_statistics.get_user_count)
    today_registered_users = await asyncio.to_thread(user_statistics.get_today_registered_user_count)
    user_count = registered_users + today_registered_users
    today_new_documents = await asyncio.to_thread(document_statistics.get_today_document_count)
    mcp_total_calls = await _get_mcp_total_calls()

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
            "mcp_total_calls": mcp_total_calls,
        },
        "period": period,
        "snapshot_date": snapshot_date,
        "is_finalized": board["is_finalized"],
        "is_embargoed": False,
    }


@router.get("/dashboard/live-stats")
@cache(expire=10, namespace="dashboard", key_builder=_dashboard_cache_key_builder)
async def get_dashboard_live_stats(
    user_statistics: UserStatisticsReader = Depends(get_user_account_repository),
    document_statistics: DocumentStatisticsReader = Depends(get_document_repository),
    catalog: ProjectCatalogQueryService = Depends(get_project_catalog_query_service),
):
    """首页统计带实时计数（10s 短缓存聚合并发访客的轮询）。

    与 summary 统计卡片同一口径但不含排行数据；前端每 10s 轮询一次，
    仅数字变化时滚筒动画滚动差位，无变化则静止。
    """
    source_counts = await _get_source_counts(document_statistics, catalog)
    total_documents = sum(source_counts.values())
    registered_users = await asyncio.to_thread(user_statistics.get_user_count)
    today_registered_users = await asyncio.to_thread(
        user_statistics.get_today_registered_user_count
    )
    user_count = registered_users + today_registered_users
    today_new_documents = await asyncio.to_thread(document_statistics.get_today_document_count)
    mcp_total_calls = await _get_mcp_total_calls()
    return {
        "total_documents": total_documents,
        "source_counts": source_counts,
        "registered_users": registered_users,
        "today_registered_users": today_registered_users,
        "user_count": user_count,
        "today_new_documents": today_new_documents,
        "mcp_total_calls": mcp_total_calls,
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
@cache(expire=10, namespace="dashboard", key_builder=_dashboard_cache_key_builder)
async def get_visitor_count(
    request: Request,
    user_statistics: UserStatisticsReader = Depends(get_user_account_repository),
):
    """返回用户数指标（10s 短缓存聚合匿名轮询，与 live-stats 口径一致）。

    行为变化：数据最多旧 10 秒；此前每次请求直查两次 COUNT。
    """
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
    repositories: ApplicationRepositories = Depends(get_application_repositories),
):
    """Return GitHub hot repositories ranked by growth + baseline + age correction."""
    from backend.app.services.ingestion.github_hot_service import get_github_hot_rank

    result = await asyncio.to_thread(
        get_github_hot_rank,
        period,
        limit,
        db=repositories.github_ingestion,
    )
    return result
