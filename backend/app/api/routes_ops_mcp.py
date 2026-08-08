from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.dependencies import get_mcp_admin_service
from backend.app.core.auth import RequireAdmin
from backend.app.models.schema_ops import (
    McpServerConfigListResponse,
    McpServerConfigRequest,
    McpServerConfigResponse,
    McpServerDeleteResponse,
    McpServerTestResponse,
)
from backend.app.services.mcp.admin_service import (
    McpAdminConflictError,
    McpAdminNotFoundError,
    McpAdminService,
    McpAdminValidationError,
    SafeMcpServerProjection,
)

router = APIRouter()


def _mcp_server_config_response(
    projection: SafeMcpServerProjection,
) -> McpServerConfigResponse:
    return McpServerConfigResponse.model_validate(projection, from_attributes=True)


# ── MCP Server 配置 ──────────────────────────────────────────────────────────


@router.get("/ops/mcp-servers", response_model=McpServerConfigListResponse, tags=["Ops"])
async def list_mcp_servers(
    _: dict = Depends(RequireAdmin),
    service: McpAdminService = Depends(get_mcp_admin_service),
) -> McpServerConfigListResponse:
    """列出 MCP Server 配置。响应不会返回明文 Token。"""
    projections = await service.list_servers()
    items = [_mcp_server_config_response(item) for item in projections]
    return McpServerConfigListResponse(items=items, total=len(items))


@router.post("/ops/mcp-servers", response_model=McpServerConfigResponse, tags=["Ops"])
async def create_mcp_server(
    request: McpServerConfigRequest,
    _: dict = Depends(RequireAdmin),
    service: McpAdminService = Depends(get_mcp_admin_service),
) -> McpServerConfigResponse:
    """创建 MCP Server 配置。auth_token 只写入，不明文返回。"""
    try:
        projection = await service.create_server(request.model_dump())
    except McpAdminValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except McpAdminConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _mcp_server_config_response(projection)


@router.put("/ops/mcp-servers/{server_id}", response_model=McpServerConfigResponse, tags=["Ops"])
async def update_mcp_server(
    server_id: int,
    request: McpServerConfigRequest,
    _: dict = Depends(RequireAdmin),
    service: McpAdminService = Depends(get_mcp_admin_service),
) -> McpServerConfigResponse:
    """更新 MCP Server 配置。auth_token 留空时保留，clear_auth_token=true 时清空。"""
    try:
        projection = await service.update_server(server_id, request.model_dump())
    except McpAdminValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except McpAdminConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except McpAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _mcp_server_config_response(projection)


@router.delete("/ops/mcp-servers/{server_id}", response_model=McpServerDeleteResponse, tags=["Ops"])
async def delete_mcp_server(
    server_id: int,
    _: dict = Depends(RequireAdmin),
    service: McpAdminService = Depends(get_mcp_admin_service),
) -> McpServerDeleteResponse:
    """删除 MCP Server 配置。"""
    try:
        await service.delete_server(server_id)
    except McpAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return McpServerDeleteResponse(status="succeeded", message="MCP Server 配置已删除。", deleted=True, id=server_id)


@router.post("/ops/mcp-servers/{server_id}/test", response_model=McpServerTestResponse, tags=["Ops"])
async def test_mcp_server(
    server_id: int,
    _: dict = Depends(RequireAdmin),
    service: McpAdminService = Depends(get_mcp_admin_service),
) -> McpServerTestResponse:
    """测试 MCP Server 连通性，只执行 initialize / tools/list，不调用任意工具。"""
    try:
        outcome = await service.test_server(server_id)
    except McpAdminNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    assert isinstance(outcome.server, SafeMcpServerProjection)
    server = _mcp_server_config_response(outcome.server)
    return McpServerTestResponse(
        status=outcome.result.get("status", "failed"),
        message=outcome.result.get("message", ""),
        server=server,
        tools=server.tools,
    )
