from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.dependencies import get_smtp_config_admin_service
from backend.app.core.auth import RequireAdmin
from backend.app.models.schema_ops import (
    SmtpConfigRequest,
    SmtpConfigResponse,
    SmtpTestRequest,
    SmtpTestResponse,
)
from backend.app.services.smtp_config_admin import (
    SmtpConfigAdminService,
    SmtpNotConfiguredError,
    SmtpTestDeliveryError,
)

router = APIRouter()


# ── SMTP 配置 ────────────────────────────────────────────────────────────────


@router.get("/ops/smtp/config", response_model=SmtpConfigResponse, tags=["Ops"])
async def get_smtp_config(
    _: dict = Depends(RequireAdmin),
    service: SmtpConfigAdminService = Depends(get_smtp_config_admin_service),
) -> SmtpConfigResponse:
    """读取生效的 SMTP 配置。响应不会返回明文密码。"""
    projection = await service.get_config()
    return SmtpConfigResponse.model_validate(projection, from_attributes=True)


@router.put("/ops/smtp/config", response_model=SmtpConfigResponse, tags=["Ops"])
async def update_smtp_config(
    request: SmtpConfigRequest,
    _: dict = Depends(RequireAdmin),
    service: SmtpConfigAdminService = Depends(get_smtp_config_admin_service),
) -> SmtpConfigResponse:
    """保存 SMTP 配置（DB 行覆盖 env，即时热生效）。

    password 留空 = 保留现状；clear_password=True = 擦除已存密码；
    host 传空 = 删除 DB 覆盖行，整体回退 env。
    """
    try:
        projection = await service.update_config(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SmtpConfigResponse.model_validate(projection, from_attributes=True)


@router.post("/ops/smtp/test", response_model=SmtpTestResponse, tags=["Ops"])
async def test_smtp_config(
    request: SmtpTestRequest,
    identity: dict = Depends(RequireAdmin),
    service: SmtpConfigAdminService = Depends(get_smtp_config_admin_service),
) -> SmtpTestResponse:
    """按最新生效配置投递测试邮件，缺省发往当前管理员的登录邮箱。"""
    to_email = str(request.to_email or "") or str(identity.get("email") or "")
    if not to_email:
        raise HTTPException(status_code=400, detail="缺少收件邮箱，请显式提供 to_email")
    try:
        result = await service.send_test_email(to_email)
    except SmtpNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    except SmtpTestDeliveryError as exc:
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    return SmtpTestResponse(**result)
