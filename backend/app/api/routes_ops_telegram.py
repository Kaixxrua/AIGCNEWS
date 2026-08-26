from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from backend.app.api.dependencies import get_telegram_config_admin_service
from backend.app.core.auth import RequireAdmin
from backend.app.models.schema_telegram_config import (
    TelegramConfigRequest,
    TelegramConfigResponse,
)
from backend.app.services.push.telegram_config_admin import TelegramConfigAdminService

router = APIRouter()


def _response(projection: object, response: Response) -> TelegramConfigResponse:
    response.headers["Cache-Control"] = "no-store"
    return TelegramConfigResponse.model_validate(projection, from_attributes=True)


@router.get("/ops/telegram/config", response_model=TelegramConfigResponse, tags=["Ops"])
async def get_telegram_config(
    response: Response,
    _: dict = Depends(RequireAdmin),
    service: TelegramConfigAdminService = Depends(get_telegram_config_admin_service),
) -> TelegramConfigResponse:
    return _response(await service.get_config(), response)


@router.put("/ops/telegram/config", response_model=TelegramConfigResponse, tags=["Ops"])
async def update_telegram_config(
    request: TelegramConfigRequest,
    response: Response,
    _: dict = Depends(RequireAdmin),
    service: TelegramConfigAdminService = Depends(get_telegram_config_admin_service),
) -> TelegramConfigResponse:
    try:
        projection = await service.update_config(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _response(projection, response)


@router.delete("/ops/telegram/config", response_model=TelegramConfigResponse, tags=["Ops"])
async def reset_telegram_config(
    response: Response,
    _: dict = Depends(RequireAdmin),
    service: TelegramConfigAdminService = Depends(get_telegram_config_admin_service),
) -> TelegramConfigResponse:
    return _response(await service.reset_config(), response)


@router.post(
    "/ops/telegram/config/webhook",
    response_model=TelegramConfigResponse,
    tags=["Ops"],
)
async def register_telegram_webhook(
    response: Response,
    _: dict = Depends(RequireAdmin),
    service: TelegramConfigAdminService = Depends(get_telegram_config_admin_service),
) -> TelegramConfigResponse:
    try:
        projection = await service.register_webhook()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _response(projection, response)
