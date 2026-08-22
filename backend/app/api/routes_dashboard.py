from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import psycopg
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi_cache.decorator import cache

from backend.app.api.dependencies import (
    get_document_repository,
    get_github_hot_board_reader,
    get_project_catalog_query_service,
    get_rank_snapshot_repository,
    get_user_account_repository,
)
from backend.app.core.postgres_database import postgres_database
from backend.app.repositories.document_repository import (
    DocumentRecentReader,
    DocumentStatisticsReader,
)
from backend.app.repositories.postgres_site_visit_repository import (
    PostgresSiteVisitRepository,
)
from backend.app.repositories.rank_snapshot_repository import RankSnapshotReader
from backend.app.repositories.site_visit_repository import (
    SiteVisitRecorder,
    SiteVisitStats,
    SiteVisitStatsReader,
)
from backend.app.repositories.user_account_repository import UserStatisticsReader
from backend.app.services.dashboard import policy
from backend.app.services.dashboard.query_service import (
    DashboardQueryService,
    GitHubHotBoardReader,
)
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


async def _get_mcp_call_counts(request: Request) -> tuple[int, int]:
    """MCP 工具调用累计次数与其中 dsh 插件来源次数。

    公开营销位口径；计数器不可用时两者静默为 0。优先读 Redis 聚合
    （主/独立 MCP 双进程共享），未绑定或故障时由服务层回退本地 JSON。
    """
    from backend.app.monitoring.mcp_redis_metrics import resolve_tool_call_metrics
    from backend.app.monitoring.mcp_tools import DSH_PLUGIN_CLIENT

    try:
        snapshot = await resolve_tool_call_metrics(request).snapshot()
        clients = snapshot.get("clients")
        dsh_entry = (
            clients.get(DSH_PLUGIN_CLIENT) if isinstance(clients, dict) else None
        )
        dsh_calls = (
            int(dsh_entry.get("calls", 0)) if isinstance(dsh_entry, dict) else 0
        )
        return int(snapshot.get("total_calls", 0)), dsh_calls
    except Exception:
        return 0, 0


def get_site_visit_repository() -> PostgresSiteVisitRepository:
    """站点访问计数仓储：按次构造（无状态，仅包裹全局连接池生命周期）。

    与 get_project_catalog_query_service 同一连接语义；定义为路由本地依赖，
    便于契约测试用 dependency_overrides 替换为假实现。
    """
    return PostgresSiteVisitRepository(postgres_database)


def _cst_today() -> date:
    tz_cst = timezone(timedelta(hours=8))
    return datetime.now(tz_cst).date()


async def _get_site_visit_stats(visits: SiteVisitStatsReader) -> SiteVisitStats:
    """读取今日/累计访问次数；数据库层故障（如迁移滞后、连接异常）静默为 0。

    只吞 psycopg 故障族：预热等直调方传错对象（Depends 默认值、None）属于
    编程错误，吞掉会把 0 写进 3600s 缓存长期污染看板，必须显式抛出让调用方
    感知。
    """
    try:
        return await asyncio.to_thread(visits.get_visit_stats, _cst_today())
    except psycopg.Error:
        logger.warning("[Dashboard] 站点访问计数查询失败，回退为 0", exc_info=True)
        return SiteVisitStats(today_visits=0, total_visits=0)


# 使用该 builder 的静态端点实际消费的 query 参数并集（见各路由 Query 声明）：
#   top/radar/summary-static/snapshot-dates: limit/source/date（看板已仅日榜，无 period）
#   x/recent: hours/limit/days_back/cursor；summary/live-stats/visitor-count 均不使用 FastAPI response cache。
# 白名单外的参数一律不进 key——前端 _t 破缓存参数如此，匿名用户构造的
# 随机参数更是如此：否则每个新参数值都生成新 key，可写爆 Redis 缓存。
_DASHBOARD_CACHE_KEY_QUERY_PARAMS = frozenset(
    {"limit", "source", "date", "hours", "days_back", "cursor"}
)


def _dashboard_cache_key_builder(
    func,
    namespace: str = "",
    request: Request | None = None,
    response: Response | None = None,
    *args,
    **kwargs,
) -> str:
    """为 dashboard 接口构建稳定 cache key，确保 date/source/limit 等参数隔离。

    关键修复：当 date 参数未传入时，显式注入 CST 当天日期到 key 中，
    防止跨日后命中前一天缓存（原先无 date 参数时 key 完全相同）。
    """
    query_params: dict[str, str] = {}
    if request is not None:
        for name in _DASHBOARD_CACHE_KEY_QUERY_PARAMS:
            value = request.query_params.get(name)
            if value is not None:
                query_params[name] = value

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


# Compatibility exports consumed by older callers (routes_mcp 已随 W6-U4 删除).
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
    date: Optional[str] = Query(
        default=None,
        description="快照日期 YYYY-MM-DD，不传默认今天；今日无快照时回溯最近"
        "有快照的日期（有界窗口），响应带 requested_date/resolved_date/stale 标记",
    ),
    rank_snapshots: RankSnapshotReader = Depends(get_rank_snapshot_repository),
    github_hot: GitHubHotBoardReader = Depends(get_github_hot_board_reader),
):
    """Return top-N daily documents ranked by vote count, optionally filtered by source and date."""
    source_type = None if (not source or source == "all") else source
    query_service = DashboardQueryService(rank_snapshots, github_hot)
    resolution = await asyncio.to_thread(
        query_service.resolve_display_snapshot_date, date, "daily", source_type
    )
    snapshot_date = resolution["resolved_date"]

    board = policy.compute_board_status(snapshot_date)

    # 静默期拦截：直接返回空列表，防止前端泄露未解禁数据
    if board["is_embargoed"]:
        return {
            "items": [],
            "total": 0,
            "period": "daily",
            "snapshot_date": snapshot_date,
            "requested_date": resolution["requested_date"],
            "resolved_date": resolution["resolved_date"],
            "stale": resolution["stale"],
            "is_finalized": board["is_finalized"],
            "is_embargoed": True,
            # 分源状态仅作信息透出：整榜闸门不变，CST 源可能已先定稿
            "source_status": policy.compute_source_status_map(snapshot_date),
        }

    docs = await asyncio.to_thread(
        query_service.get_docs_for_date, snapshot_date, "daily", source_type, 500
    )
    deduped = policy.dedupe_docs(docs)
    top_items = deduped[:limit]

    # 模块四-1：为每条文档注入完整 pdf_media_url
    top_items = [policy.enrich_doc_pdf_url(dict(doc), request) for doc in top_items]

    return {
        "items": top_items,
        "total": len(top_items),
        "period": "daily",
        "snapshot_date": snapshot_date,
        "requested_date": resolution["requested_date"],
        "resolved_date": resolution["resolved_date"],
        "stale": resolution["stale"],
        "is_finalized": board["is_finalized"],
        "is_embargoed": False,
        "source_status": policy.compute_source_status_map(snapshot_date),
    }


def _published_at_within(value: Any, start: datetime, end: datetime) -> bool:
    """published_at ISO 串解析后落在 [start, end) 半开区间；空值/无法解析一律剔除。"""
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return start <= parsed < end


# X 看板日期位移上限：与前端快照日期清单长度一致，防止深翻扫全表
_X_RECENT_MAX_DAYS_BACK = 60

# x/recent keyset 续页游标：base64url(JSON [published_at, score, id])，
# 只编码文档的公开排序位置，不含任何凭据；与仓储层 X 分支
# ORDER BY published_at DESC, score DESC, id DESC 一一对应。
_X_RECENT_CURSOR_VERSION = 1


def _x_recent_cursor_from_doc(doc: Dict[str, Any]) -> Optional[str]:
    published_at = doc.get("published_at")
    doc_id = doc.get("id")
    if not isinstance(published_at, str) or not published_at or not doc_id:
        return None
    raw_score = doc.get("raw_score")
    score = doc.get("score")
    try:
        score_value = float(
            raw_score if raw_score not in (None, "") else (score or 0)
        )
    except (TypeError, ValueError):
        score_value = 0.0
    payload = [_X_RECENT_CURSOR_VERSION, published_at, score_value, str(doc_id)]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _parse_x_recent_cursor(value: str) -> Optional[tuple[str, float, str]]:
    """解析续页游标；任何非法输入返回 None（调用方回退第一页，绝不 400）。"""
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeDecodeError):
        return None
    if (
        not isinstance(payload, list)
        or len(payload) != 4
        or payload[0] != _X_RECENT_CURSOR_VERSION
        or not isinstance(payload[1], str)
        or not payload[1]
        or not isinstance(payload[3], str)
        or not payload[3]
    ):
        return None
    try:
        score_value = float(payload[2])
    except (TypeError, ValueError):
        return None
    return payload[1], score_value, payload[3]


@router.get("/dashboard/x/recent")
@cache(expire=600, namespace="dashboard", key_builder=_dashboard_cache_key_builder)
async def get_x_recent(
    hours: int = Query(default=24, ge=1, le=72),
    days_back: int = Query(default=0, ge=0, le=_X_RECENT_MAX_DAYS_BACK),
    limit: int = Query(default=500, ge=1, le=500),
    cursor: Optional[str] = Query(
        default=None,
        description="keyset 续页游标（上一页响应的 next_cursor），不传返回第一页",
    ),
    documents: DocumentRecentReader = Depends(get_document_repository),
):
    """滚动 N 小时（默认 24）发布的 X 推文，按发布时间新到旧；days_back 整体回移窗口。

    窗口 = [now - days_back·24h - hours, now - days_back·24h]：days_back=0 即
    「最近 N 小时」（默认视图），days_back=1 即「昨天此时此刻往前 N 小时」，
    供 X 看板日期选择器按整数天滑动。不走快照/定稿/静默期语义：数据直查
    documents 表，用户时区由前端展示层换算。key 含 days_back/cursor 不含
    前端 _t 破缓存参数。冷算 ~2.3s（500 条），TTL 600s 覆盖采集 cadence
    （5 分钟）：每次采集成功后 clear_and_warm_dashboard_cache 先清后暖本 key，
    数据新鲜度由「距上次采集」界定而非 TTL；TTL 只在采集停摆时兜底过期。
    行为变化：缓存过期口径 120s→600s，采集正常时实际新鲜度不变。

    分页：单页上限 500。满页时响应携带 ``next_cursor``/``has_more``，前端
    以其续查下一页（keyset 严格递减，跨页去重）；默认请求（无 cursor）的
    字段与首页语义完全不变，旧客户端无感知。
    """
    end = datetime.now(timezone.utc) - timedelta(days=days_back)
    cutoff = end - timedelta(hours=hours)
    keyset_after = _parse_x_recent_cursor(cursor) if cursor else None
    docs = await asyncio.to_thread(
        lambda: documents.list_recent_by_source(
            "x",
            since_iso=cutoff.isoformat(),
            until_iso=end.isoformat(),
            limit=limit,
            keyset_after=keyset_after,
        )
    )
    items = [doc for doc in docs if _published_at_within(doc.get("published_at"), cutoff, end)]
    has_more = len(items) >= limit
    next_cursor = _x_recent_cursor_from_doc(items[-1]) if has_more and items else None
    return {
        "items": items,
        "total": len(items),
        "period": "daily",
        "window_hours": hours,
        "days_back": days_back,
        "has_more": has_more and next_cursor is not None,
        "next_cursor": next_cursor,
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
    date: Optional[str] = Query(
        default=None,
        description="快照日期 YYYY-MM-DD，不传默认今天；今日无快照时回溯最近"
        "有快照的日期（有界窗口），响应带 requested_date/resolved_date/stale 标记",
    ),
    rank_snapshots: RankSnapshotReader = Depends(get_rank_snapshot_repository),
    github_hot: GitHubHotBoardReader = Depends(get_github_hot_board_reader),
):
    """Return trend radar chart data computed from filtered top documents."""
    source_type = None if (not source or source == "all") else source
    query_service = DashboardQueryService(rank_snapshots, github_hot)
    resolution = await asyncio.to_thread(
        query_service.resolve_display_snapshot_date, date, "daily", source_type
    )
    snapshot_date = resolution["resolved_date"]

    board = policy.compute_board_status(snapshot_date)

    # 静默期拦截
    if board["is_embargoed"]:
        return {
            "radar": [],
            "doc_count": 0,
            "period": "daily",
            "snapshot_date": snapshot_date,
            "requested_date": resolution["requested_date"],
            "resolved_date": resolution["resolved_date"],
            "stale": resolution["stale"],
            "is_finalized": board["is_finalized"],
            "is_embargoed": True,
        }

    docs = await asyncio.to_thread(
        query_service.get_docs_for_date,
        snapshot_date,
        "daily",
        source_type,
        max(limit, 100),
    )
    radar = policy.score_categories(docs[:limit])
    return {
        "radar": radar,
        "doc_count": len(docs[:limit]),
        "period": "daily",
        "snapshot_date": snapshot_date,
        "requested_date": resolution["requested_date"],
        "resolved_date": resolution["resolved_date"],
        "stale": resolution["stale"],
        "is_finalized": board["is_finalized"],
        "is_embargoed": False,
    }


async def _build_dashboard_static_payload(
    *,
    date: Optional[str],
    rank_snapshots: RankSnapshotReader,
    github_hot: GitHubHotBoardReader,
) -> dict[str, Any]:
    """Build the date-addressed ranking portion of the dashboard response."""
    query_service = DashboardQueryService(rank_snapshots, github_hot)
    resolution = await asyncio.to_thread(
        query_service.resolve_display_snapshot_date, date, "daily", None
    )
    snapshot_date = resolution["resolved_date"]
    board = policy.compute_board_status(snapshot_date)
    base = {
        "period": "daily",
        "snapshot_date": snapshot_date,
        "requested_date": resolution["requested_date"],
        "resolved_date": resolution["resolved_date"],
        "stale": resolution["stale"],
        "is_finalized": board["is_finalized"],
        "is_embargoed": board["is_embargoed"],
    }
    if board["is_embargoed"]:
        return {"top_list": [], "radar": [], **base}

    docs = await asyncio.to_thread(
        query_service.get_docs_for_date, snapshot_date, "daily", None, 500
    )
    deduped = policy.dedupe_docs(docs)
    return {
        "top_list": deduped[:10],
        "radar": policy.score_categories(deduped[:50]),
        **base,
    }


@router.get("/dashboard/summary-static")
@cache(expire=3600, namespace="dashboard", key_builder=_dashboard_cache_key_builder)
async def get_dashboard_summary_static(
    date: Optional[str] = Query(
        default=None,
        description="快照日期 YYYY-MM-DD，不传默认今天；今日无快照时回溯最近有快照的日期",
    ),
    rank_snapshots: RankSnapshotReader = Depends(get_rank_snapshot_repository),
    github_hot: GitHubHotBoardReader = Depends(get_github_hot_board_reader),
):
    """Return the cacheable ranking/date portion of the dashboard."""
    return await _build_dashboard_static_payload(
        date=date, rank_snapshots=rank_snapshots, github_hot=github_hot
    )


async def _get_dashboard_stats(
    request: Request,
    *,
    user_statistics: UserStatisticsReader,
    document_statistics: DocumentStatisticsReader,
    catalog: ProjectCatalogQueryService,
    visits: SiteVisitStatsReader,
) -> dict[str, Any]:
    """Read current global dashboard counters; never cache this aggregate."""
    source_counts = await _get_source_counts(document_statistics, catalog)
    registered_users = await asyncio.to_thread(user_statistics.get_user_count)
    today_registered_users = await asyncio.to_thread(
        user_statistics.get_today_registered_user_count
    )
    visit_stats = await _get_site_visit_stats(visits)
    mcp_total_calls, mcp_dsh_calls = await _get_mcp_call_counts(request)
    return {
        "total_documents": sum(source_counts.values()),
        "source_counts": source_counts,
        "registered_users": registered_users,
        "today_registered_users": today_registered_users,
        "user_count": registered_users + today_registered_users,
        "today_new_documents": await asyncio.to_thread(
            document_statistics.get_today_document_count
        ),
        "today_unique_visitors": visit_stats.today_visits,
        "today_visits": visit_stats.today_visits,
        "total_visits": visit_stats.total_visits,
        "mcp_total_calls": mcp_total_calls,
        "mcp_dsh_calls": mcp_dsh_calls,
    }


@router.get("/dashboard/summary")
async def get_dashboard_summary(
    request: Request,
    response: Response,
    date: Optional[str] = Query(
        default=None,
        description="快照日期 YYYY-MM-DD，不传默认今天；今日无快照时回溯最近"
        "有快照的日期（有界窗口），响应带 requested_date/resolved_date/stale 标记",
    ),
    user_statistics: UserStatisticsReader = Depends(get_user_account_repository),
    document_statistics: DocumentStatisticsReader = Depends(get_document_repository),
    rank_snapshots: RankSnapshotReader = Depends(get_rank_snapshot_repository),
    catalog: ProjectCatalogQueryService = Depends(get_project_catalog_query_service),
    github_hot: GitHubHotBoardReader = Depends(get_github_hot_board_reader),
    visits: SiteVisitStatsReader = Depends(get_site_visit_repository),
):
    """Return the legacy combined payload with fresh global counters."""
    if response is not None:
        response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    static = await _build_dashboard_static_payload(
        date=date, rank_snapshots=rank_snapshots, github_hot=github_hot
    )
    stats = await _get_dashboard_stats(
        request,
        user_statistics=user_statistics,
        document_statistics=document_statistics,
        catalog=catalog,
        visits=visits,
    )
    return {**static, "stats": stats}


@router.get("/dashboard/live-stats")
async def get_dashboard_live_stats(
    request: Request,
    response: Response,
    user_statistics: UserStatisticsReader = Depends(get_user_account_repository),
    document_statistics: DocumentStatisticsReader = Depends(get_document_repository),
    catalog: ProjectCatalogQueryService = Depends(get_project_catalog_query_service),
    visits: SiteVisitStatsReader = Depends(get_site_visit_repository),
):
    """首页统计带实时计数（由前端每 10 秒轮询，不缓存响应）。

    与 summary 统计卡片同一口径但不含排行数据；前端每 10s 轮询一次，
    仅数字变化时滚筒动画滚动差位，无变化则静止。
    """
    response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    source_counts = await _get_source_counts(document_statistics, catalog)
    total_documents = sum(source_counts.values())
    registered_users = await asyncio.to_thread(user_statistics.get_user_count)
    today_registered_users = await asyncio.to_thread(
        user_statistics.get_today_registered_user_count
    )
    user_count = registered_users + today_registered_users
    today_new_documents = await asyncio.to_thread(document_statistics.get_today_document_count)
    visit_stats = await _get_site_visit_stats(visits)
    mcp_total_calls, mcp_dsh_calls = await _get_mcp_call_counts(request)
    return {
        "total_documents": total_documents,
        "source_counts": source_counts,
        "registered_users": registered_users,
        "today_registered_users": today_registered_users,
        "user_count": user_count,
        "today_new_documents": today_new_documents,
        "today_unique_visitors": visit_stats.today_visits,
        "today_visits": visit_stats.today_visits,
        "total_visits": visit_stats.total_visits,
        "mcp_total_calls": mcp_total_calls,
        "mcp_dsh_calls": mcp_dsh_calls,
    }


@router.get("/dashboard/snapshot-dates")
@cache(expire=60, namespace="dashboard", key_builder=_dashboard_cache_key_builder)
async def get_snapshot_dates(
    limit: int = Query(default=60, ge=1, le=365),
    source: Optional[str] = Query(default=None),
    rank_snapshots: RankSnapshotReader = Depends(get_rank_snapshot_repository),
    github_hot: GitHubHotBoardReader = Depends(get_github_hot_board_reader),
):
    """返回指定来源有日榜快照记录的日期列表（降序）。

    github 日榜已切换 v5 热度指标口径，可用日期以指标表为准，
    保证历史日期选择器与榜单实际可读数据一致。
    """
    source_type = None if (not source or source == "all") else source
    if source_type == "github":
        dates = await asyncio.to_thread(
            github_hot.list_github_hot_dates,
            limit=limit,
        )
    else:
        dates = await asyncio.to_thread(
            rank_snapshots.get_snapshot_dates,
            limit,
            source_type,
            "daily",
        )
    return {
        "dates": dates,
        "total": len(dates),
        "source": source_type or "all",
        "period": "daily",
    }


@router.get("/dashboard/visitor-count")
async def get_visitor_count(
    request: Request,
    response: Response,
    user_statistics: UserStatisticsReader = Depends(get_user_account_repository),
    visits: SiteVisitStatsReader = Depends(get_site_visit_repository),
):
    """返回用户数与访问计数指标（不缓存，与 live-stats 口径一致）。

    行为变化：today_unique_visitors 此前是 user_count 的占位别名，现为真实
    今日访问次数（纯次数口径，与 today_visits 相同）；新增 total_visits 累计字段。
    """
    if response is not None:
        response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    registered_users = await asyncio.to_thread(user_statistics.get_user_count)
    today_registered_users = await asyncio.to_thread(user_statistics.get_today_registered_user_count)
    user_count = registered_users + today_registered_users
    visit_stats = await _get_site_visit_stats(visits)
    return {
        "user_count": user_count,
        "registered_users": registered_users,
        "today_registered_users": today_registered_users,
        "today_unique_visitors": visit_stats.today_visits,
        "today_visits": visit_stats.today_visits,
        "total_visits": visit_stats.total_visits,
    }


@router.post("/dashboard/visit")
async def record_site_visit(
    visits: SiteVisitRecorder = Depends(get_site_visit_repository),
):
    """站点访问 beacon：前端每 tab 会话首次进入发一次（sessionStorage 守卫）。

    纯次数口径——每次调用当天（CST）计数 +1，不按访客去重；返回计数后的
    最新值，前端统计卡片可即时刷新，无需等待 live-stats 轮询。
    """
    stats = await asyncio.to_thread(visits.record_visit, _cst_today())
    return {"today_visits": stats.today_visits, "total_visits": stats.total_visits}
