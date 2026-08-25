from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from backend.app.api.dependencies import get_oauth_config_admin_service
from backend.app.core.auth import RequireAdmin
from backend.app.models.schema_oauth_config import OAuthConfigRequest, OAuthConfigResponse
from backend.app.services.auth.oauth.config_admin import OAuthConfigAdminService

router = APIRouter()


def _response(projection: object, response: Response) -> OAuthConfigResponse:
    response.headers["Cache-Control"] = "no-store"
    return OAuthConfigResponse.model_validate(projection, from_attributes=True)


@router.get("/ops/oauth/config", response_model=OAuthConfigResponse, tags=["Ops"])
async def get_oauth_config(
    response: Response,
    _: dict = Depends(RequireAdmin),
    service: OAuthConfigAdminService = Depends(get_oauth_config_admin_service),
) -> OAuthConfigResponse:
    return _response(await service.get_config(), response)


@router.put("/ops/oauth/config", response_model=OAuthConfigResponse, tags=["Ops"])
async def update_oauth_config(
    request: OAuthConfigRequest,
    response: Response,
    _: dict = Depends(RequireAdmin),
    service: OAuthConfigAdminService = Depends(get_oauth_config_admin_service),
) -> OAuthConfigResponse:
    try:
        projection = await service.update_config(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _response(projection, response)


@router.delete("/ops/oauth/config", response_model=OAuthConfigResponse, tags=["Ops"])
async def reset_oauth_config(
    response: Response,
    _: dict = Depends(RequireAdmin),
    service: OAuthConfigAdminService = Depends(get_oauth_config_admin_service),
) -> OAuthConfigResponse:
    return _response(await service.reset_config(), response)
