from __future__ import annotations

import asyncio
import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator

from backend.app.api.dependencies import (
    get_mcp_access_token_repository,
    get_user_account_repository,
)
from backend.app.core.auth import (
    RequireUser,
    create_access_token,
    hash_mcp_token,
    hash_password,
    verify_password,
)
from backend.app.core.client_ip import client_ip_from_request
from backend.app.core.config import settings
from backend.app.repositories.mcp_access_token_repository import McpAccessTokenManager
from backend.app.repositories.user_account_repository import UserAccountRepository
from backend.app.services.auth import account_lifecycle
from backend.app.services.auth.adapters import build_account_lifecycle
from backend.app.services.auth.default_admin_bootstrap import (
    password_change_required_for_email,
    uses_configured_default_credentials,
)
from backend.app.services.auth.rate_limit import RateLimitExceededError, hit_rate_limit
from backend.app.services.email_service import (
    EmailService,
    OtpDeliveryUnavailableError,
    OtpSendRateLimitedError,
    build_email_service,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# 认证敏感端点 IP 级固定窗口限速（防在线爆破与 OTP 滥用）
_AUTH_RATE_LIMIT_WINDOW_SECONDS = 600
_OTP_SEND_RATE_LIMIT = 5
_AUTH_ATTEMPT_RATE_LIMIT = 10
# 登录追加 per-账号（email）固定窗口节流：防分布式 IP 对单一账号爆破，
# 窗口与上限对齐 per-IP 口径，实现复用同一 hit_rate_limit。
_LOGIN_ACCOUNT_RATE_LIMIT = 10


async def _enforce_rate_limit(
    request: Request,
    *,
    action: str,
    limit: int,
    identity: str | None = None,
) -> None:
    """执行固定窗口限速；Redis 不可用时放行并告警（可用性优先于限速严格性）。

    identity 缺省为可信代理感知的客户端 IP；per-账号节流显式传 email。
    """
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return
    try:
        await hit_rate_limit(
            redis_client,
            action=action,
            identity=identity if identity is not None else client_ip_from_request(request),
            limit=limit,
            window_seconds=_AUTH_RATE_LIMIT_WINDOW_SECONDS,
        )
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后再试",
        ) from exc
    except Exception:
        logger.warning(
            "[Auth] rate limit check failed, allowing request", exc_info=True
        )


def _get_email_service(request: Request) -> EmailService:
    """从 app.state 获取 Redis 并构造 EmailService 实例。"""
    redis_client = getattr(request.app.state, "redis", None)
    return build_email_service(redis_client)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SendEmailOtpRequest(BaseModel):
    email: EmailStr


def _validate_email_code(value: str) -> str:
    if not re.fullmatch(r"\d{6}", value):
        raise ValueError("email_code must be exactly 6 digits")
    return value


def _validate_new_password(value: str) -> str:
    if len(value) < 6:
        raise ValueError("password must be at least 6 characters")
    if len(value.encode("utf-8")) > 72:
        raise ValueError("password must not exceed 72 UTF-8 bytes")
    return value


class RegisterRequest(BaseModel):
    email: EmailStr
    email_code: str
    password: str

    @field_validator("email_code")
    @classmethod
    def validate_email_code(cls, value: str) -> str:
        return _validate_email_code(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_new_password(value)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    email_code: str
    new_password: str

    @field_validator("email_code")
    @classmethod
    def validate_email_code(cls, value: str) -> str:
        return _validate_email_code(value)

    @field_validator("new_password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_new_password(value)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return _validate_new_password(value)


MCP_TOKEN_SCOPES = frozenset({"projects:favorites:read"})
MCP_CLIENT_TYPES = frozenset({"claude", "cursor", "vscode", "other"})


class CreateMcpTokenRequest(BaseModel):
    client_type: str
    client_label: str = Field(default="", max_length=128)
    scopes: list[str] = Field(default_factory=lambda: ["projects:favorites:read"])
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

    - 60 秒防刷（Redis email:lock）+ IP 级限速
    - 仅开发环境（ENV=development/dev 且 SMTP_HOST 为空）将 OTP 打印到日志；
      其他环境 SMTP 未配置时拒绝发码并返回 503
    """
    await _enforce_rate_limit(request, action="auth.send_email_otp", limit=_OTP_SEND_RATE_LIMIT)
    email_svc = _get_email_service(request)
    try:
        await email_svc.send_otp(str(body.email))
    except OtpSendRateLimitedError as exc:
        raise HTTPException(status_code=429, detail=exc.detail) from exc
    except OtpDeliveryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from exc
    return {"detail": "验证码已发送"}


@router.post("/auth/send-password-reset-otp", summary="发送密码重置邮箱验证码")
async def send_password_reset_otp(
    body: SendEmailOtpRequest,
    request: Request,
    response: Response,
    repository: UserAccountRepository = Depends(get_user_account_repository),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    await _enforce_rate_limit(request, action="auth.send_reset_otp", limit=_OTP_SEND_RATE_LIMIT)
    lifecycle = build_account_lifecycle(
        repository=repository,
        otp=_get_email_service(request),
        password_hasher=hash_password,
    )
    try:
        await lifecycle.request_password_reset_otp(email=str(body.email))
    except OtpSendRateLimitedError as exc:
        raise HTTPException(status_code=429, detail=exc.detail) from exc
    except OtpDeliveryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from exc
    return {"detail": "如果该邮箱已注册，验证码将发送至该邮箱"}


@router.post("/auth/reset-password", summary="使用邮箱验证码重置密码")
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    response: Response,
    repository: UserAccountRepository = Depends(get_user_account_repository),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    await _enforce_rate_limit(request, action="auth.reset_password", limit=_AUTH_ATTEMPT_RATE_LIMIT)
    lifecycle = build_account_lifecycle(
        repository=repository,
        otp=_get_email_service(request),
        password_hasher=hash_password,
    )
    try:
        await lifecycle.reset_password(
            email=str(body.email),
            email_code=body.email_code,
            new_password=body.new_password,
        )
    except account_lifecycle.InvalidOtp as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码错误或已过期",
        ) from exc
    except account_lifecycle.PasswordResetFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="密码重置失败，请稍后重试",
        ) from exc
    return {"detail": "密码重置成功"}


@router.post("/auth/me/password", summary="已登录改密（当前密码校验，免邮箱验证码）")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: UserAccountRepository = Depends(get_user_account_repository),
) -> dict[str, Any]:
    """凭当前密码修改密码，不依赖邮箱验证码。

    自托管没有可用 SMTP 时这是唯一的密码轮换路径；默认管理员种子账号
    借此脱离公开默认密码。JWT 无 email 声明视为身份无效（401）。
    """
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    await _enforce_rate_limit(
        request, action="auth.change_password", limit=_AUTH_ATTEMPT_RATE_LIMIT
    )
    email = str(current_user.get("email") or "")
    if not email:
        raise HTTPException(status_code=401, detail="用户身份无效")
    lifecycle = build_account_lifecycle(
        repository=repository,
        password_hasher=hash_password,
        password_verifier=verify_password,
    )
    try:
        await lifecycle.change_password(
            email=email,
            current_password=body.current_password,
            new_password=body.new_password,
        )
    except account_lifecycle.InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前密码错误",
        ) from exc
    except account_lifecycle.PasswordChangeFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="密码修改失败，请稍后重试",
        ) from exc
    return {"detail": "密码已修改"}


@router.post("/auth/register", summary="用户注册（邮箱 + 验证码 + 密码）")
async def register(
    body: RegisterRequest,
    request: Request,
    repository: UserAccountRepository = Depends(get_user_account_repository),
) -> dict[str, Any]:
    """
    注册新用户。

    1. 校验邮箱验证码（consume=False 先不删除）
    2. 检查邮箱是否已注册
    3. bcrypt 哈希密码后写库
    4. 消耗验证码
    """
    await _enforce_rate_limit(request, action="auth.register", limit=_AUTH_ATTEMPT_RATE_LIMIT)
    lifecycle = build_account_lifecycle(
        repository=repository,
        otp=_get_email_service(request),
        password_hasher=hash_password,
    )
    try:
        result = await lifecycle.register(
            email=str(body.email),
            email_code=body.email_code,
            password=body.password,
        )
    except account_lifecycle.InvalidOtp as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码错误或已过期",
        ) from exc
    except account_lifecycle.AccountAlreadyExists as exc:
        # 中性文案（对齐密码重置的防枚举口径）：不直接确认邮箱已注册
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="注册失败，请检查邮箱验证码或稍后重试",
        ) from exc
    return {"detail": "注册成功", "user_id": result.user_id}


@router.post("/auth/login", summary="登录（邮箱 + 密码）")
async def login(
    body: LoginRequest,
    request: Request,
    repository: UserAccountRepository = Depends(get_user_account_repository),
) -> dict[str, Any]:
    """
    用户登录，返回 JWT。

    - 查库验证邮箱 + 密码
    - 签发 JWT（payload 含 user_id、role、email）
    """
    await _enforce_rate_limit(request, action="auth.login", limit=_AUTH_ATTEMPT_RATE_LIMIT)
    # per-账号节流：分布式 IP 对同一邮箱的爆破归并到单一账号桶；
    # 域名归一与登录生命周期同口径，防大小写变体拆桶
    await _enforce_rate_limit(
        request,
        action="auth.login.account",
        limit=_LOGIN_ACCOUNT_RATE_LIMIT,
        identity=account_lifecycle._normalize_email_domain(str(body.email).strip()),
    )
    lifecycle = build_account_lifecycle(
        repository=repository,
        password_verifier=verify_password,
        token_issuer=create_access_token,
    )
    try:
        result = await lifecycle.login(
            email=str(body.email),
            password=body.password,
        )
    except account_lifecycle.InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        ) from exc
    return {
        "access_token": result.access_token,
        "token_type": result.token_type,
        "role": result.role,
        # 种子默认凭据登录提示：前端据此常驻提醒改密（免 SMTP 改密端点）
        "password_change_required": uses_configured_default_credentials(
            email=str(body.email),
            password=body.password,
            configured_email=settings.DEFAULT_ADMIN_EMAIL,
            configured_password=settings.DEFAULT_ADMIN_PASSWORD,
        ),
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
    repository: McpAccessTokenManager = Depends(
        get_mcp_access_token_repository
    ),
) -> list[dict[str, Any]]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return await asyncio.to_thread(
        repository.list_user_mcp_tokens,
        user_id=_user_id(current_user),
    )


@router.post("/auth/me/mcp-tokens", summary="创建当前用户的 MCP Token")
async def create_mcp_token(
    body: CreateMcpTokenRequest,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: McpAccessTokenManager = Depends(
        get_mcp_access_token_repository
    ),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    token = "aigc_mcp_" + secrets.token_urlsafe(32)
    item = await asyncio.to_thread(
        repository.create_user_mcp_token,
        user_id=_user_id(current_user),
        token_hash=hash_mcp_token(token),
        token_hint=f"{token[:12]}...{token[-4:]}",
        scopes=body.scopes,
        client_type=body.client_type,
        client_label=body.client_label.strip(),
        expires_at=body.expires_at,
    )
    metadata = item.pop("token_metadata")
    return {"token": token, "token_metadata": metadata, "replaced_count": item["replaced_count"]}


@router.delete("/auth/me/mcp-tokens/{token_id}", summary="删除当前用户的 MCP Token")
async def delete_mcp_token(
    token_id: int,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: McpAccessTokenManager = Depends(
        get_mcp_access_token_repository
    ),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    deleted = await asyncio.to_thread(
        repository.delete_user_mcp_token,
        user_id=_user_id(current_user),
        token_id=token_id,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="MCP Token 不存在")
    return {"deleted": True, "id": token_id}


@router.get("/auth/me", summary="获取当前登录用户信息")
async def me(
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: UserAccountRepository = Depends(get_user_account_repository),
) -> dict[str, Any]:
    """
    返回当前登录用户信息（从 JWT payload 提取）。
    需要携带有效 Bearer Token。
    password_change_required 以库内哈希为准（仅种子默认邮箱账号触发查询）。
    """
    change_required = await asyncio.to_thread(
        password_change_required_for_email,
        repository=repository,
        email=str(current_user.get("email") or ""),
        configured_email=settings.DEFAULT_ADMIN_EMAIL,
        configured_password=settings.DEFAULT_ADMIN_PASSWORD,
        verify_password=verify_password,
    )
    return {
        "user_id": current_user.get("user_id"),
        "email": current_user.get("email"),
        "role": current_user.get("role"),
        "password_change_required": change_required,
    }
