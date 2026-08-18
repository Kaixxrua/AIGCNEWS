"""版本化程序化 API（``/api/v1/*``）：agent/插件的项目检索入口。

与网站 ``/api/projects`` 同一个项目库、同一个查询服务，但走商业配额面：
Bearer MCP token 认证（``OptionalMcpUser``，McpConnect 页签发的同一个
token 即 API key）；匿名调用按 IP 走日配额，登录用户按会员档位走月配额，
与 MCP 通道共享同一个配额池（见 services/api_access/quota）。网站浏览
端点保持不变、永远免费——收费面只覆盖程序化调用。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from backend.app.api.dependencies import get_project_catalog_query_service
from backend.app.core.auth import OptionalMcpUser
from backend.app.models.schema_projects import (
    GitHubProjectCategoriesResponse,
    GitHubProjectsResponse,
    ProjectScope,
    PublicProjectSort,
)
from backend.app.services.api_access.quota import (
    API_RATE_LIMIT_WINDOW_SECONDS,
    ApiQuotaExceededError,
    enforce_api_search_rate_limit,
)
from backend.app.services.auth.rate_limit import RateLimitExceededError
from backend.app.services.mcp.inbound.context import McpAuthorizationContext
from backend.app.services.project_catalog.query_service import ProjectCatalogQueryService

router = APIRouter()


def _rate_limited_response() -> JSONResponse:
    """分钟级突发桶 429 投影：无配额域字段，与配额超限区分。"""

    return JSONResponse(
        {
            "detail": (
                "Rate limit exceeded; slow down and retry after "
                f"{API_RATE_LIMIT_WINDOW_SECONDS} seconds."
            ),
            "error": "rate_limited",
        },
        status_code=429,
        headers={"Retry-After": str(API_RATE_LIMIT_WINDOW_SECONDS)},
    )


def _quota_exceeded_response(exc: ApiQuotaExceededError) -> JSONResponse:
    """分层配额 429 投影：quota_scope/tier/limit/retry_after + 分档升级引导。

    匿名→aigcnews.cn/mcp 登录建 token 或开通 VIP，免费→开通 VIP，
    会员→告知窗口重置时间；与 MCP quota 投影保持中英双语和同一商业口径。
    额度数字走 exc.limit 插值，不随档位调整发生文案漂移。
    """

    if exc.quota_scope == "daily":
        message = (
            f"已达今日匿名调用上限（{exc.limit} 次/天，按 IP 计）。"
            "请前往 https://aigcnews.cn/mcp 登录并创建 MCP token 获得月度配额，"
            "或前往 https://aigcnews.cn/membership 开通 VIP 享更高额度。"
            f"Anonymous daily quota exhausted ({exc.limit} calls/day per IP): "
            "sign in at https://aigcnews.cn/mcp to create an MCP token for "
            "a monthly quota, or upgrade to VIP at https://aigcnews.cn/membership."
        )
    elif exc.tier == "member":
        message = (
            f"本月 VIP 额度已用完（{exc.limit} 次/月），"
            f"配额窗口将于约 {exc.retry_after} 秒后重置。"
            f"VIP monthly quota exhausted ({exc.limit} calls/month); "
            f"the window resets in about {exc.retry_after} seconds."
        )
    else:
        message = (
            f"本月免费额度已用完（{exc.limit} 次/月）。"
            "请前往 https://aigcnews.cn/membership 开通 VIP 享更高额度，"
            f"或等待配额窗口重置（约 {exc.retry_after} 秒后）。"
            f"Free monthly quota exhausted ({exc.limit} calls/month): "
            "upgrade to VIP at https://aigcnews.cn/membership for a higher "
            "quota, or wait for the window to reset."
        )
    return JSONResponse(
        {
            "detail": message,
            "error": "quota_exceeded",
            "quota_scope": exc.quota_scope,
            "tier": exc.tier,
            "limit": exc.limit,
            "retry_after": exc.retry_after,
        },
        status_code=429,
        headers={"Retry-After": str(exc.retry_after)},
    )


async def _enforce_or_project(
    request: Request, authorization: McpAuthorizationContext
) -> JSONResponse | None:
    """执行双层限速；超限时返回 429 投影，未超限返回 None。"""

    try:
        await enforce_api_search_rate_limit(
            request,
            user_id=authorization.user_id,
            role=authorization.role,
            membership_tier=authorization.membership_tier,
        )
    except ApiQuotaExceededError as exc:
        return _quota_exceeded_response(exc)
    except RateLimitExceededError:
        return _rate_limited_response()
    return None


# 以下两个响应封装与 routes_github_projects 保持同形（插件/客户端共用
# 解析）；刻意不 import 其私有函数——热点路由文件解耦，信封漂移由
# 契约测试守护。
def _projects_envelope(
    result: dict[str, Any],
    *,
    min_stars: int,
    scope: str,
    category: str,
    subcategory: str,
    q: str,
    sort: str,
) -> GitHubProjectsResponse:
    return GitHubProjectsResponse(
        items=result["items"],
        total=int(result["total"]),
        page=int(result["page"]),
        page_size=int(result["page_size"]),
        has_next=int(result["page"]) * int(result["page_size"]) < int(result["total"]),
        min_stars=min_stars,
        scope=scope,
        category=category,
        subcategory=subcategory,
        q=q,
        sort=sort,
        source="github",
    )


def _categories_envelope(result: dict[str, Any], *, min_stars: int) -> GitHubProjectCategoriesResponse:
    total = int(result.get("total") or 0)
    today_count = int(result.get("today_count") or 0)
    recommended_count = int(result.get("recommended_count") or 0)
    category_items = result.get("items") or []
    scope_items = [
        {"slug": "all", "name": "全部", "name_zh": "全部", "name_en": "All", "count": total, "kind": "scope", "scope": "all", "children": []},
        {"slug": "recommended", "name": "站长推荐", "name_zh": "站长推荐", "name_en": "Recommended", "count": recommended_count, "kind": "scope", "scope": "recommended", "children": []},
        {"slug": "today", "name": "今日暴涨", "name_zh": "今日暴涨", "name_en": "Trending Today", "count": today_count, "kind": "scope", "scope": "today", "children": []},
    ]
    return GitHubProjectCategoriesResponse(
        items=[*scope_items, *category_items],
        total=total,
        today_count=today_count,
        recommended_count=recommended_count,
        min_stars=min_stars,
        source="github",
    )


@router.get(
    "/v1/projects/search",
    response_model=GitHubProjectsResponse,
    tags=["Projects API"],
)
async def search_projects_v1(
    request: Request,
    scope: ProjectScope = Query(default="all"),
    category: str = Query(default="", max_length=64),
    subcategory: str = Query(default="", max_length=64),
    q: str = Query(default="", max_length=120),
    language: str = Query(default="", max_length=64),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=60),
    sort: PublicProjectSort | None = Query(default=None),
    mcp_user: dict[str, Any] | None = Depends(OptionalMcpUser),
    catalog: ProjectCatalogQueryService = Depends(get_project_catalog_query_service),
) -> Any:
    """程序化项目检索：与 MCP search_github_ai_projects 同库同配额池。"""
    authorization = McpAuthorizationContext(mcp_user)
    rejection = await _enforce_or_project(request, authorization)
    if rejection is not None:
        return rejection
    clean_category = category.strip()
    clean_subcategory = subcategory.strip()
    clean_q = q.strip()
    page_result = await catalog.list_public_projects(
        scope=scope,
        category=clean_category,
        subcategory=clean_subcategory,
        q=clean_q,
        language=language.strip(),
        page=page,
        page_size=page_size,
        sort=sort,
        user_id=authorization.user_id or None,
    )
    return _projects_envelope(
        page_result.result,
        min_stars=catalog.min_stars,
        scope=scope,
        category=clean_category,
        subcategory=clean_subcategory,
        q=clean_q,
        sort=page_result.effective_sort,
    )


@router.get(
    "/v1/projects/categories",
    response_model=GitHubProjectCategoriesResponse,
    tags=["Projects API"],
)
async def list_project_categories_v1(
    request: Request,
    mcp_user: dict[str, Any] | None = Depends(OptionalMcpUser),
    catalog: ProjectCatalogQueryService = Depends(get_project_catalog_query_service),
) -> Any:
    """程序化分类树：与检索入口同一限速/配额口径。"""
    authorization = McpAuthorizationContext(mcp_user)
    rejection = await _enforce_or_project(request, authorization)
    if rejection is not None:
        return rejection
    result = await catalog.get_public_categories()
    return _categories_envelope(result, min_stars=catalog.min_stars)
