from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr

from backend.app.core.auth import (
    RequireUser,
    create_access_token,
    hash_password,
    verify_password,
)
from backend.app.core.config import settings
from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.services.email_service import EmailService

router = APIRouter()

# 固定邀请码（内测阶段）
_INVITE_CODE = "internal_testing"


def _get_email_service(request: Request) -> EmailService:
    """从 app.state 获取 Redis 并构造 EmailService 实例。"""
    redis_client = getattr(request.app.state, "redis", None)
    return EmailService(
        redis_client=redis_client,
        smtp_host=settings.SMTP_HOST,
        smtp_port=settings.SMTP_PORT,
        smtp_username=settings.SMTP_USERNAME,
        smtp_password=settings.SMTP_PASSWORD,
        smtp_from_email=settings.SMTP_FROM_EMAIL,
        smtp_from_name=settings.SMTP_FROM_NAME,
        smtp_use_tls=settings.SMTP_USE_TLS,
    )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SendEmailOtpRequest(BaseModel):
    email: EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    email_code: str
    password: str
    invite_code: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/auth/send-email-otp", summary="发送邮箱验证码")
async def send_email_otp(body: SendEmailOtpRequest, request: Request) -> dict[str, Any]:
    """
    发送邮箱验证码。

    - 60 秒防刷（Redis email:lock）
    - dev 模式（SMTP_HOST 为空）将 OTP 打印到日志
    """
    email_svc = _get_email_service(request)
    await email_svc.send_otp(str(body.email))
    return {"detail": "验证码已发送"}


@router.post("/auth/register", summary="用户注册（邮箱 + 验证码 + 邀请码 + 密码）")
async def register(body: RegisterRequest, request: Request) -> dict[str, Any]:
    """
    注册新用户。

    1. 校验邀请码
    2. 校验邮箱验证码（consume=False 先不删除）
    3. 检查邮箱是否已注册
    4. bcrypt 哈希密码后写库
    5. 消耗验证码
    """
    # Step 1: 校验邀请码
    if body.invite_code != _INVITE_CODE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="邀请码无效",
        )

    # Step 2: 校验邮箱验证码（先不消耗）
    email_svc = _get_email_service(request)
    verified = await email_svc.verify_otp(
        str(body.email), body.email_code, consume=False
    )
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码错误或已过期",
        )

    # Step 3: 检查邮箱是否已注册
    db = MySQLRepository()
    existing = await asyncio.to_thread(db.get_user_by_email, str(body.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该邮箱已注册",
        )

    # Step 4: 哈希密码并写库
    hashed = hash_password(body.password)
    new_id = await asyncio.to_thread(
        db.create_user_with_email,
        str(body.email),
        hashed,
        body.invite_code,
        "user",
        "",  # username 默认为空
    )

    # Step 5: 全部成功后消耗验证码
    await email_svc.consume_otp(str(body.email))

    return {"detail": "注册成功", "user_id": new_id}


@router.post("/auth/login", summary="登录（邮箱 + 密码）")
async def login(body: LoginRequest) -> dict[str, Any]:
    """
    用户登录，返回 JWT。

    - 查库验证邮箱 + 密码
    - 签发 JWT（payload 含 user_id、role、email）
    """
    db = MySQLRepository()
    user = await asyncio.to_thread(db.get_user_by_email, str(body.email))
    if user is None or not verify_password(body.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        )

    token = create_access_token(
        {
            "user_id": user["id"],
            "role": user["role"],
            "email": user["email"],
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
        "email": current_user.get("email"),
        "role": current_user.get("role"),
    }
