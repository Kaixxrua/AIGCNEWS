from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from backend.app.api.dependencies import (
    get_application_repositories,
    get_briefing_repository,
)
from backend.app.api.mcp_contracts import input_schema, validate_iso_date
from backend.app.core.auth import OptionalMcpUser
from backend.app.repositories.application_repository_factory import ApplicationRepositories
from backend.app.repositories.briefing_repository import BriefingReader
from backend.app.services.mcp.inbound.application import (
    McpPromptInputError,
    McpProtocolApplication,
    McpProtocolDependencies,
    McpProtocolResponse,
    McpResourceInputError,
    _get_prompt,
    _parse_resource_uri,
    _prompt_arg,
    _prompt_message,
    _read_resource,
    _resolve_report_date,
    _resource_dashboard_summary,
    _resource_report_latest,
    _resource_tool_args,
)
from backend.app.services.mcp.inbound.catalog import (
    MCP_HOST_INSTRUCTIONS,
    MCP_PRIVATE_TOOL_NAMES,
    MCP_PROMPTS,
    MCP_PROTOCOL_VERSION,
    MCP_PUBLIC_TOOL_NAMES,
    MCP_RESOURCES,
    MCP_RESOURCE_TEMPLATES,
    MCP_SERVER_NAME,
    MCP_SERVER_VERSION,
    MCP_TOOLS,
    MAX_REQUEST_BYTES,
    MAX_RESOURCE_TEXT_CHARS,
    MAX_TOOL_RESULT_CHARS,
    _DATE_RE,
    _JSONRPC_INTERNAL_ERROR,
    _JSONRPC_INVALID_PARAMS,
    _JSONRPC_INVALID_REQUEST,
    _JSONRPC_METHOD_NOT_FOUND,
    _JSONRPC_PARSE_ERROR,
    _PERIOD_CHOICES,
    _PRIVATE_MCP_TOOLS,
    _PROJECT_FALLBACK_POLICY,
    _SOURCE_CHOICES,
)
from backend.app.services.mcp.inbound.context import (
    McpAuthorizationContext,
    McpRequestError,
    McpSessionTransport,
    parse_mcp_request,
)
from backend.app.services.mcp.inbound.responses import (
    _json_safe,
    _resource_content,
    _tool_error,
    _tool_response,
)
from backend.app.services.mcp.inbound.tools import (
    MCP_TOOL_REGISTRY,
    McpToolContext,
    McpToolInputError,
    _TOOL_HANDLERS,
    _call_tool,
    _clean_choice,
    _clean_string,
    _public_doc,
    _public_project_item,
    _search_project_library,
    _tool_get_paper_detail,
    _tool_get_project_categories,
    _tool_get_project_library,
    _tool_get_top_items,
    _tool_search_documents,
    _tool_search_github_ai_projects,
    _tool_search_github_projects,
    _tool_search_my_project_favorites,
    _tool_search_papers,
    _validated_tool_args,
)

router = APIRouter()
_MCP_SESSION_TRANSPORT = McpSessionTransport()


def _mcp_headers(session_id: str | None = None) -> dict[str, str]:
    """Compatibility seam for callers retained until final cleanup."""

    return _MCP_SESSION_TRANSPORT.headers(session_id)


def _jsonrpc_result(
    request_id: Any,
    result: dict[str, Any],
    *,
    session_id: str | None = None,
) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "result": result},
        headers=_mcp_headers(session_id),
    )


def _jsonrpc_error(request_id: Any, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        },
        headers=_mcp_headers(),
    )


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
) -> Response:
    authorization = McpAuthorizationContext(mcp_user)
    request.state.mcp_user = authorization.user
    request.state.papers_repository = repositories.documents
    request.state.document_repository = repositories.documents
    request.state.rank_snapshot_repository = repositories.rank_snapshots
    request.state.project_collection_repository = repositories.project_collections
    tool_context = McpToolContext(
        user=authorization.user,
        documents=repositories.documents,
        papers=repositories.documents,
        rank_snapshots=repositories.rank_snapshots,
        project_collection=repositories.project_collections,
        request=request,
    )
    application = McpProtocolApplication(
        McpProtocolDependencies(
            authorization=authorization,
            tools=tool_context,
            briefing_repository=briefing_repository,
            session_transport=_MCP_SESSION_TRANSPORT,
        )
    )

    try:
        inbound = await parse_mcp_request(request)
    except McpRequestError as exc:
        return _http_response(application.error(exc.request_id, exc.code, exc.message))
    return _http_response(await application.dispatch(inbound))
