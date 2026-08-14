from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.app.api.dependencies import get_email_pool_config_admin_service
from backend.app.core.auth import RequireAdmin
from backend.app.models.schema_ops import (
    EmailPoolConfigRequest,
    EmailPoolConfigResponse,
    EmailPoolTestRequest,
    EmailPoolTestResponse,
)
from backend.app.services.email_pool_config_admin import (
    EmailPoolConfigAdminService,
    EmailPoolNotConfiguredError,
    EmailPoolTestDeliveryError,
)

router = APIRouter()


# ── 邮件池配置 ───────────────────────────────────────────────────────────────


@router.get(
    "/ops/email-pool/config", response_model=EmailPoolConfigResponse, tags=["Ops"]
)
async def get_email_pool_config(
    _: dict = Depends(RequireAdmin),
    service: EmailPoolConfigAdminService = Depends(get_email_pool_config_admin_service),
) -> EmailPoolConfigResponse:
    """读取生效的邮件池配置。响应不会返回明文密码。"""
    projection = await service.get_config()
    return EmailPoolConfigResponse.model_validate(projection, from_attributes=True)


@router.put(
    "/ops/email-pool/config", response_model=EmailPoolConfigResponse, tags=["Ops"]
)
async def update_email_pool_config(
    request: EmailPoolConfigRequest,
    _: dict = Depends(RequireAdmin),
    service: EmailPoolConfigAdminService = Depends(get_email_pool_config_admin_service),
) -> EmailPoolConfigResponse:
    """保存邮件池配置（DB 行覆盖 EMAIL_POOL_JSON env，即时热生效）。

    逐 entry：password 留空 = 按 name 保留已存密码；clear_password=True =
    擦除；entries 传空数组 = 删除 DB 覆盖行，整体回退 env。
    """
    try:
        projection = await service.update_config(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return EmailPoolConfigResponse.model_validate(projection, from_attributes=True)


@router.post(
    "/ops/email-pool/test", response_model=EmailPoolTestResponse, tags=["Ops"]
)
async def test_email_pool_config(
    request: EmailPoolTestRequest,
    identity: dict = Depends(RequireAdmin),
    service: EmailPoolConfigAdminService = Depends(get_email_pool_config_admin_service),
) -> EmailPoolTestResponse:
    """经真实邮件池（含 failover 与配额计数）投递测试邮件，
    缺省发往当前管理员的登录邮箱。"""
    to_email = str(request.to_email or "") or str(identity.get("email") or "")
    if not to_email:
        raise HTTPException(status_code=400, detail="缺少收件邮箱，请显式提供 to_email")
    try:
        result = await service.send_test_email(to_email)
    except EmailPoolNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    except EmailPoolTestDeliveryError as exc:
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    return EmailPoolTestResponse(**result)
