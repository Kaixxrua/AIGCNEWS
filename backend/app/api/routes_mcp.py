from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from backend.app.api.dependencies import (
    get_application_repositories,
    get_briefing_repository,
    get_project_catalog_query_service,
    get_project_search_runtime,
)
from backend.app.core.auth import OptionalMcpUser
from backend.app.monitoring.mcp_redis_metrics import resolve_tool_call_metrics
from backend.app.repositories.application_repository_factory import (
    ApplicationRepositories,
)
from backend.app.repositories.briefing_repository import BriefingReader
from backend.app.services.auth.rate_limit import RateLimitExceededError
from backend.app.services.mcp.inbound.application import (
    McpProtocolApplication,
    McpProtocolDependencies,
    McpProtocolResponse,
)
from backend.app.services.mcp.inbound.context import (
    McpAuthorizationContext,
    McpRequestError,
    McpSessionTransport,
    parse_mcp_request,
)
from backend.app.services.mcp.inbound.rate_limit import (
    McpQuotaExceededError,
    enforce_mcp_rate_limit,
    mcp_quota_exceeded_projection,
    mcp_rate_limited_projection,
)
from backend.app.services.mcp.inbound.tools import McpToolContext
from backend.app.services.project_catalog.query_service import ProjectCatalogQueryService

router = APIRouter()
_MCP_SESSION_TRANSPORT = McpSessionTransport()


def _http_response(projection: McpProtocolResponse) -> Response:
    if projection.body is None:
        return Response(
            status_code=projection.status_code,
            headers=projection.headers,
        )
    return JSONResponse(
        projection.body,
        status_code=projection.status_code,
        headers=projection.headers,
    )


@router.post("/mcp", tags=["MCP"])
async def mcp_endpoint(
    request: Request,
    mcp_user: dict[str, Any] | None = Depends(OptionalMcpUser),
    briefing_repository: BriefingReader = Depends(get_briefing_repository),
    repositories: ApplicationRepositories = Depends(get_application_repositories),
    project_search_runtime: Any = Depends(get_project_search_runtime),
    catalog_queries: ProjectCatalogQueryService = Depends(
        get_project_catalog_query_service
    ),
) -> Response:
    authorization = McpAuthorizationContext(mcp_user)
    tool_context = McpToolContext(
        user=authorization.user,
        documents=repositories.documents,
        papers=repositories.documents,
        rank_snapshots=repositories.rank_snapshots,
        project_collection=repositories.project_collections,
        request=request,
        project_searcher=project_search_runtime.search_projects,
        catalog_queries=catalog_queries,
    )
    application = McpProtocolApplication(
        McpProtocolDependencies(
            authorization=authorization,
            tools=tool_context,
            briefing_repository=briefing_repository,
            session_transport=_MCP_SESSION_TRANSPORT,
            # Redis 聚合由 lifespan 绑进 app.state；未绑定（Redis 故障、
            # 测试不经 lifespan）回退模块级 JSON 门面，行为同 Redis 化之前。
            tool_call_metrics=resolve_tool_call_metrics(request),
        )
    )

    try:
        inbound = await parse_mcp_request(request)
    except McpRequestError as exc:
        return _http_response(application.error(exc.request_id, exc.code, exc.message))
    try:
        # 分层配额（Red）：role/membership_tier 以 MCP token 关联的库内用户
        # 为准（get_user_by_mcp_token_hash JOIN 已带列，零额外查询）；
        # 匿名 user=None → 上下文属性回退 user/free 走 IP 日配额。
        await enforce_mcp_rate_limit(
            request,
            method=inbound.method,
            user_id=authorization.user_id,
            role=authorization.role,
            membership_tier=authorization.membership_tier,
        )
    except McpQuotaExceededError as exc:
        return _http_response(
            mcp_quota_exceeded_projection(inbound.request_id, exc)
        )
    except RateLimitExceededError:
        return _http_response(mcp_rate_limited_projection(inbound.request_id))
    return _http_response(await application.dispatch(inbound))
