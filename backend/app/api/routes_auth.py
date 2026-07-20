from __future__ import annotations

import asyncio
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator

from backend.app.core.auth import (
    RequireUser,
    create_access_token,
    hash_mcp_token,
    hash_password,
    verify_password,
)
from backend.app.core.config import settings
from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.services.email_service import EmailService

router = APIRouter()


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


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


MCP_TOKEN_SCOPES = frozenset({"projects:favorites:read"})
MCP_CLIENT_TYPES = frozenset({"claude", "cursor", "vscode", "other"})


class CreateMcpTokenRequest(BaseModel):
    client_type: str
    client_label: str = Field(default="", max_length=128)
    scopes: list[str] = Field(default_factory=lambda: ["projects:favorites:read"])
    multi_open: bool = False
    expires_at: datetime | None = None

    @field_validator("client_type")
    @classmethod
    def validate_client_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in MCP_CLIENT_TYPES:
            raise ValueError(f"client_type must be one of: {', '.join(sorted(MCP_CLIENT_TYPES))}")
        return normalized

    @field_validator("scopes")
    @classmethod
    def validate_scopes(cls, value: list[str]) -> list[str]:
        scopes = list(dict.fromkeys(scope.strip() for scope in value if scope.strip()))
        unknown = set(scopes) - MCP_TOKEN_SCOPES
        if unknown or not scopes:
            raise ValueError(f"scopes must be a non-empty subset of: {', '.join(sorted(MCP_TOKEN_SCOPES))}")
        return scopes

    @field_validator("expires_at")
    @classmethod
    def validate_expiry(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        if value <= datetime.now(timezone.utc):
            raise ValueError("expires_at must be in the future")
        return value.astimezone(timezone.utc).replace(tzinfo=None)


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


@router.post("/auth/register", summary="用户注册（邮箱 + 验证码 + 密码）")
async def register(body: RegisterRequest, request: Request) -> dict[str, Any]:
    """
    注册新用户。

    1. 校验邮箱验证码（consume=False 先不删除）
    2. 检查邮箱是否已注册
    3. bcrypt 哈希密码后写库
    4. 消耗验证码
    """
    # Step 1: 校验邮箱验证码（先不消耗）
    email_svc = _get_email_service(request)
    verified = await email_svc.verify_otp(
        str(body.email), body.email_code, consume=False
    )
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码错误或已过期",
        )

    # Step 2: 检查邮箱是否已注册
    db = MySQLRepository()
    existing = await asyncio.to_thread(db.get_user_by_email, str(body.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该邮箱已注册",
        )

    # Step 3: 哈希密码并写库
    hashed = hash_password(body.password)
    new_id = await asyncio.to_thread(
        db.create_user_with_email,
        str(body.email),
        hashed,
        "",
        "user",
        "",  # username 默认为空
    )

    # Step 4: 全部成功后消耗验证码
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


def _user_id(user: dict[str, Any]) -> int:
    try:
        user_id = int(user.get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    if user_id <= 0:
        raise HTTPException(status_code=401, detail="用户身份无效")
    return user_id


@router.get("/auth/me/mcp-tokens", summary="列出当前用户的 MCP Token")
async def list_mcp_tokens(
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    db = MySQLRepository()
    return await asyncio.to_thread(db.list_user_mcp_tokens, user_id=_user_id(current_user))


@router.post("/auth/me/mcp-tokens", summary="创建当前用户的 MCP Token")
async def create_mcp_token(
    body: CreateMcpTokenRequest,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    token = "aigc_mcp_" + secrets.token_urlsafe(32)
    db = MySQLRepository()
    item = await asyncio.to_thread(
        db.create_user_mcp_token,
        user_id=_user_id(current_user),
        token_hash=hash_mcp_token(token),
        token_hint=f"{token[:12]}...{token[-4:]}",
        scopes=body.scopes,
        client_type=body.client_type,
        client_label=body.client_label.strip(),
        expires_at=body.expires_at,
        multi_open=body.multi_open,
    )
    metadata = item.pop("token_metadata")
    return {"token": token, "token_metadata": metadata, "replaced_count": item["replaced_count"]}


@router.delete("/auth/me/mcp-tokens/{token_id}", summary="删除当前用户的 MCP Token")
async def delete_mcp_token(
    token_id: int,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    db = MySQLRepository()
    deleted = await asyncio.to_thread(
        db.delete_user_mcp_token,
        user_id=_user_id(current_user),
        token_id=token_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="MCP Token 不存在")
    return {"deleted": True, "id": token_id}


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
