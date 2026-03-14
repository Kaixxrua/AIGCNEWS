from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from backend.app.core.auth import (
    RequireUser,
    create_access_token,
    hash_password,
    verify_password,
)
from backend.app.core.config import settings
from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.services.sms_service import SmsService

router = APIRouter()

_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


def _validate_phone(phone: str) -> None:
    """校验手机号格式，不合法时抛 422。"""
    if not _PHONE_RE.match(phone):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="手机号格式错误，请输入 11 位大陆手机号",
        )


def _get_sms_service(request: Request) -> SmsService:
    """从 app.state 获取 Redis 并构造 SmsService 实例。"""
    redis_client = getattr(request.app.state, "redis", None)
    return SmsService(redis_client=redis_client, sms_api_key=settings.SMS_API_KEY)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SendOtpRequest(BaseModel):
    phone: str


class RegisterRequest(BaseModel):
    phone: str
    password: str
    sms_code: str


class LoginRequest(BaseModel):
    phone: str
    password: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/auth/send-otp", summary="发送短信验证码")
async def send_otp(body: SendOtpRequest, request: Request) -> dict[str, Any]:
    """
    发送短信验证码。

    - 校验 11 位大陆手机号格式
    - 60 秒防刷（Redis sms:lock）
    - dev 模式（SMS_API_KEY 为空）将 OTP 打印到日志
    """
    _validate_phone(body.phone)
    sms = _get_sms_service(request)
    await sms.send_otp(body.phone)
    return {"detail": "验证码已发送"}


@router.post("/auth/register", summary="用户注册（手机号 + 密码 + 验证码）")
async def register(body: RegisterRequest, request: Request) -> dict[str, Any]:
    """
    注册新用户。

    1. 校验手机号格式
    2. 校验短信验证码
    3. 检查手机号是否已注册
    4. bcrypt 哈希密码后写库
    """
    _validate_phone(body.phone)

    sms = _get_sms_service(request)
    # consume=False：先只校验验证码正确性，不立即删除
    # 避免后续步骤（hash_password / 写库）失败时验证码被白白消耗
    verified = await sms.verify_otp(body.phone, body.sms_code, consume=False)
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码错误或已过期",
        )

    db = MySQLRepository()
    existing = await asyncio.to_thread(db.get_user_by_phone, body.phone)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该手机号已注册",
        )

    hashed = hash_password(body.password)
    new_id = await asyncio.to_thread(
        db.create_user,
        body.phone,
        "",  # username 默认为空，用户可后续修改
        hashed,
        "user",
    )
    # 所有步骤成功后，才删除验证码 key（防止重复注册同一验证码）
    await sms.consume_otp(body.phone)
    return {"detail": "注册成功", "user_id": new_id}


@router.post("/auth/login", summary="登录（手机号 + 密码）")
async def login(body: LoginRequest) -> dict[str, Any]:
    """
    用户登录，返回 JWT。

    - 查库验证手机号 + 密码
    - 签发 JWT（payload 含 user_id、role、phone）
    """
    _validate_phone(body.phone)

    db = MySQLRepository()
    user = await asyncio.to_thread(db.get_user_by_phone, body.phone)
    if user is None or not verify_password(body.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="手机号或密码错误",
        )

    token = create_access_token(
        {
            "user_id": user["id"],
            "role": user["role"],
            "phone": user["phone"],
        }
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user["role"],
    }


@router.get("/auth/me", summary="获取当前登录用户信息")
async def me(current_user: dict[str, Any] = Depends(RequireUser)) -> dict[str, Any]:
    """
    返回当前登录用户信息（从 JWT payload 提取）。
    需要携带有效 Bearer Token。
    """
    return {
        "user_id": current_user.get("user_id"),
        "phone": current_user.get("phone"),
        "role": current_user.get("role"),
    }
