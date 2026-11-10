"""Public exact description reads and authenticated, metered generation."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.app.api.dependencies import get_operations_runtime, get_project_descriptions_service
from backend.app.core.auth import OptionalMcpUser
from backend.app.core.client_ip import client_ip_from_request
from backend.app.core.operations import ApplicationOperationsRuntime
from backend.app.models.schema_project_descriptions import (
    MAX_DESCRIPTION_REPOS,
    ProjectDescriptionRequest,
    ProjectDescriptionsResponse,
    normalize_description_repo,
)
from backend.app.services.api_access.quota import ApiQuotaExceededError
from backend.app.services.auth.rate_limit import RateLimitExceededError
from backend.app.services.mcp.inbound.context import McpAuthorizationContext
from backend.app.services.project_catalog.descriptions_service import (
    DescriptionBusy,
    DescriptionNotPublic,
    ProjectDescriptionsService,
)

router = APIRouter()


async def _description_request(request: Request) -> ProjectDescriptionRequest:
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(415, "请使用 application/json。")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 2048:
            raise HTTPException(413, "请求内容过大。")
    try:
        return ProjectDescriptionRequest.model_validate(json.loads(body))
    except (ValueError, ValidationError, UnicodeError) as exc:
        raise HTTPException(422, "请求须包含有效 repo；gameDetails、refreshPoster 必须为布尔值，重新找海报需要 gameDetails=true。") from exc


def _error_response(exc: Exception) -> JSONResponse:
    headers = {"Cache-Control": "no-store"}
    if isinstance(exc, ApiQuotaExceededError):
        headers["Retry-After"] = str(exc.retry_after)
        return JSONResponse({
            "error": "quota_exceeded", "detail": "AIGCNEWS 程序化调用额度已用完，请在额度重置后重试。",
            "quota_scope": exc.quota_scope, "tier": exc.tier, "limit": exc.limit,
            "retry_after": exc.retry_after, "identity_kind": exc.identity_kind,
        }, status_code=429, headers=headers)
    if isinstance(exc, (RateLimitExceededError, DescriptionBusy)):
        retry = exc.retry_after if isinstance(exc, DescriptionBusy) else 60
        headers["Retry-After"] = str(retry)
        return JSONResponse({"error": "rate_limited", "detail": "中文简介请求较多，请稍后重试。", "retry_after": retry}, status_code=429, headers=headers)
    if isinstance(exc, DescriptionNotPublic):
        return JSONResponse({"error": "not_available", "detail": "无法读取此公开仓库。"}, status_code=404, headers=headers)
    # Redis, database and provider errors can contain credentials. Do not expose
    # raw exception text or silently bypass a failed quota/lease operation.
    return JSONResponse({"error": "temporarily_unavailable", "detail": "中文简介服务暂时不可用，请稍后重试。"}, status_code=503, headers=headers)


@router.get("/v1/projects/descriptions", response_model=ProjectDescriptionsResponse, response_model_exclude_none=True, tags=["Projects API"])
async def read_project_descriptions(
    request: Request, response: Response,
    repos: str = Query(..., min_length=3, max_length=7100),
    gameDetails: bool = Query(False),
    service: ProjectDescriptionsService = Depends(get_project_descriptions_service),
) -> Any:
    parts = repos.split(",")
    if not 1 <= len(parts) <= MAX_DESCRIPTION_REPOS:
        raise HTTPException(422, "一次可读取 1–50 个仓库。")
    try:
        names = list(dict.fromkeys(normalize_description_repo(part.strip()) for part in parts))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    try:
        items = await service.read(names, redis=getattr(request.app.state, "redis", None), client_ip=client_ip_from_request(request), game_details=gameDetails)
        return {"items": items, "pollAfter": 3}
    except Exception as exc:
        return _error_response(exc)


@router.post("/v1/projects/descriptions", response_model=ProjectDescriptionsResponse, response_model_exclude_none=True, tags=["Projects API"])
async def request_project_description(
    request: Request, response: Response,
    payload: ProjectDescriptionRequest = Depends(_description_request),
    user: dict[str, Any] | None = Depends(OptionalMcpUser),
    service: ProjectDescriptionsService = Depends(get_project_descriptions_service),
    operations: ApplicationOperationsRuntime = Depends(get_operations_runtime),
) -> Any:
    authorization = McpAuthorizationContext(user)
    if not authorization.is_authenticated or authorization.user_id <= 0:
        raise HTTPException(401, "生成中文简介需要 AIGCNEWS MCP Token。", headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"})
    # Public repository generation uses the authenticated account's API quota,
    # just like public project search. Issued scopes govern personal favorites
    # and tracking only; the token issuer does not grant a generic "read" scope.
    response.headers["Cache-Control"] = "no-store"
    try:
        item = await service.request(payload.repo, redis=getattr(request.app.state, "redis", None), authorization=authorization, operations=operations, game_details=payload.gameDetails, refresh_poster=payload.refreshPoster)
        response.status_code = 202 if item["status"] == "pending" else 200
        return {"items": [item], "pollAfter": 3}
    except Exception as exc:
        return _error_response(exc)
