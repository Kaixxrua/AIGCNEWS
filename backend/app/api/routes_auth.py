from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from psycopg import errors as pg_errors
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from backend.app.api.dependencies import (
    get_feed_token_repository,
    get_mcp_access_token_repository,
    get_oauth_identity_repository,
    get_user_account_repository,
)
from backend.app.core.auth import (
    RequireUser,
    create_access_token,
    hash_feed_token,
    hash_mcp_token,
    hash_password,
    verify_password,
)
from backend.app.core.client_ip import client_ip_from_request
from backend.app.core.config import settings
from backend.app.repositories.feed_token_repository import FeedTokenRepository
from backend.app.repositories.mcp_access_token_repository import (
    DshMcpTokenManager,
    McpAccessTokenManager,
)
from backend.app.repositories.postgres_feed_token_repository import (
    FeedTokenSecretError,
    build_feed_token_secret_box,
)
from backend.app.repositories.postgres_mcp_access_token_repository import (
    DshMcpTokenSecretError,
    build_dsh_mcp_token_secret_box,
)
from backend.app.repositories.user_account_repository import UserAccountRepository
from backend.app.services.auth import account_lifecycle
from backend.app.services.auth.adapters import build_account_lifecycle
from backend.app.services.auth.avatar import MAX_AVATAR_BYTES, normalize_avatar
from backend.app.services.auth.default_admin_bootstrap import (
    password_change_required_for_email,
    uses_configured_default_credentials,
)
from backend.app.services.auth.rate_limit import (
    RateLimitExceededError,
    clear_login_failures,
    get_login_failure_count,
    hit_rate_limit,
    record_login_failure,
)
from backend.app.services.email_service import (
    EmailService,
    OtpDeliveryUnavailableError,
    OtpSendRateLimitedError,
    build_email_service,
)
from backend.app.services.membership.tiers import resolve_effective_tier

logger = logging.getLogger(__name__)

router = APIRouter()

# 认证敏感端点 IP 级固定窗口限速（防在线爆破与 OTP 滥用）
_AUTH_RATE_LIMIT_WINDOW_SECONDS = 600
_OTP_SEND_RATE_LIMIT = 5
_AUTH_ATTEMPT_RATE_LIMIT = 10
# 登录追加 per-账号（email）固定窗口节流：防分布式 IP 对单一账号爆破，
# 窗口与上限对齐 per-IP 口径，实现复用同一 hit_rate_limit。
_LOGIN_ACCOUNT_RATE_LIMIT = 10
# 登录失败锁定：同一账号窗口内"密码核验失败"达上限即拒绝后续登录
# （含密码正确者，直到窗口过期），与上面的请求级限速叠加，进一步压低
# 在线爆破的有效猜测预算（20 次/小时/账号）
_LOGIN_FAILURE_LOCKOUT_THRESHOLD = 20
_LOGIN_FAILURE_WINDOW_SECONDS = 3600


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


async def _enforce_login_lockout(request: Request, *, email: str) -> None:
    """失败计数达上限的账号直接 429；Redis 异常时放行并告警（与限速同口径）。"""
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return
    try:
        failures = await get_login_failure_count(redis_client, email=email)
    except Exception:
        logger.warning(
            "[Auth] login lockout check failed, allowing request", exc_info=True
        )
        return
    if failures >= _LOGIN_FAILURE_LOCKOUT_THRESHOLD:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="失败次数过多，账号已临时锁定，请稍后再试",
        )


async def _record_login_failure(request: Request, *, email: str) -> None:
    """记录一次密码核验失败；Redis 异常仅告警（计数缺失不阻断登录流程）。"""
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return
    try:
        await record_login_failure(
            redis_client, email=email, window_seconds=_LOGIN_FAILURE_WINDOW_SECONDS
        )
    except Exception:
        logger.warning("[Auth] login failure recording failed", exc_info=True)


async def _clear_login_failures(request: Request, *, email: str) -> None:
    """登录成功后清零失败计数；Redis 异常仅告警（残留计数随窗口 TTL 过期）。"""
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return
    try:
        await clear_login_failures(redis_client, email=email)
    except Exception:
        logger.warning("[Auth] login failure cleanup failed", exc_info=True)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class SendEmailOtpRequest(BaseModel):
    email: EmailStr


def _validate_email_code(value: str) -> str:
    if not re.fullmatch(r"\d{6}", value):
        raise ValueError("email_code must be exactly 6 digits")
    return value


# 常见弱口令黑名单（大小写不敏感）：命中即拒绝。
# admin123456 是本仓库自托管引导的历史默认口令（DEFAULT_ADMIN_PASSWORD
# 的出厂值），必须阻止用户在改密时回退到它；短于最小长度的条目保留作
# 纵深防御（最小长度下调时仍拦截）。
_WEAK_PASSWORD_BLOCKLIST = frozenset(
    {
        "123456",
        "12345678",
        "123456789",
        "1234567890",
        "111111",
        "000000",
        "abc123",
        "qwerty",
        "qwertyuiop",
        "password",
        "password123",
        "letmein",
        "iloveyou",
        "admin123",
        "admin123456",
        "aigcnews",
        "aigcnews123",
    }
)


def _validate_new_password(value: str) -> str:
    # bcrypt 成本与在线爆破模型：8 位起 + 弱口令黑名单；
    # 72 字节上限是 bcrypt 输入截断边界（超限静默截断会造成可用性歧义）
    if len(value) < 8:
        raise ValueError("password must be at least 8 characters")
    if len(value.encode("utf-8")) > 72:
        raise ValueError("password must not exceed 72 UTF-8 bytes")
    if value.lower() in _WEAK_PASSWORD_BLOCKLIST:
        raise ValueError("password is too common, choose a stronger one")
    return value


def _validate_username(value: str) -> str:
    # users.username 是 VARCHAR(64)：先裁剪再限长，超限直接拒绝而非静默截断
    normalized = value.strip()
    if not normalized:
        raise ValueError("username must not be empty")
    if len(normalized) > 64:
        raise ValueError("username must not exceed 64 characters")
    return normalized


class RegisterRequest(BaseModel):
    email: EmailStr
    email_code: str
    password: str
    username: str

    @field_validator("email_code")
    @classmethod
    def validate_email_code(cls, value: str) -> str:
        return _validate_email_code(value)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return _validate_new_password(value)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return _validate_username(value)


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
    email_code: str
    new_password: str

    @field_validator("email_code")
    @classmethod
    def validate_email_code(cls, value: str) -> str:
        return _validate_email_code(value)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return _validate_new_password(value)


class UpdateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        return _validate_username(value)


class SendEmailChangeNewOtpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_email: EmailStr


class ConfirmEmailChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_email: EmailStr
    current_code: str
    new_code: str

    @field_validator("current_code", "new_code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        return _validate_email_code(value)


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


@router.post("/auth/me/send-password-change-otp", summary="发送改密邮箱验证码（已登录）")
async def send_change_password_otp(
    request: Request,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: UserAccountRepository = Depends(get_user_account_repository),
) -> dict[str, Any]:
    """向当前登录用户的账号邮箱发送改密验证码（purpose=password_change）。"""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    await _enforce_rate_limit(
        request, action="auth.send_change_otp", limit=_OTP_SEND_RATE_LIMIT
    )
    lifecycle = build_account_lifecycle(
        repository=repository,
        otp=_get_email_service(request),
        password_hasher=hash_password,
    )
    try:
        await lifecycle.request_change_password_otp(user_id=_user_id(current_user))
    except account_lifecycle.InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户身份无效",
        ) from exc
    except OtpSendRateLimitedError as exc:
        raise HTTPException(status_code=429, detail=exc.detail) from exc
    except OtpDeliveryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from exc
    return {"detail": "验证码已发送至当前账号邮箱"}


@router.post("/auth/me/password", summary="已登录改密（邮箱验证码校验）")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: UserAccountRepository = Depends(get_user_account_repository),
) -> dict[str, Any]:
    """凭邮箱验证码修改密码（验证码替代当前密码，产品决策：强制邮箱验证）。

    账户归属只取自 RequireUser 提供的 user_id；当前邮箱由生命周期从数据库读取。
    无 SMTP 的自托管环境无可用改密路径（免验证码旧口令路径已按决策移除）。
    """
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    await _enforce_rate_limit(
        request, action="auth.change_password", limit=_AUTH_ATTEMPT_RATE_LIMIT
    )
    lifecycle = build_account_lifecycle(
        repository=repository,
        otp=_get_email_service(request),
        password_hasher=hash_password,
        password_verifier=verify_password,
        token_issuer=create_access_token,
    )
    try:
        result = await lifecycle.change_password(
            user_id=_user_id(current_user),
            email_code=body.email_code,
            new_password=body.new_password,
        )
    except account_lifecycle.InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户身份无效",
        ) from exc
    except account_lifecycle.InvalidOtp as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码错误或已过期",
        ) from exc
    except account_lifecycle.PasswordChangeFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="密码修改失败，请稍后重试",
        ) from exc
    return {
        "access_token": result.access_token,
        "token_type": result.token_type,
        "changed": result.changed,
    }


# ---------------------------------------------------------------- 邮箱换绑
# 目标账户只取自 RequireUser 的 user_id；当前邮箱由生命周期从数据库读取，
# 绝不信任 JWT email 声明或请求体。confirm 返回数据库权威账户投影，
# 前端据此一次性刷新（无需再发一次 /auth/me）。


@router.post(
    "/auth/me/email-change/send-current",
    summary="发送换绑验证码到当前邮箱（已登录）",
)
async def send_email_change_current_otp(
    request: Request,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: UserAccountRepository = Depends(get_user_account_repository),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    await _enforce_rate_limit(
        request, action="auth.send_email_change_otp", limit=_OTP_SEND_RATE_LIMIT
    )
    lifecycle = build_account_lifecycle(
        repository=repository,
        otp=_get_email_service(request),
    )
    try:
        await lifecycle.request_email_change_current_otp(user_id=_user_id(current_user))
    except account_lifecycle.EmailChangeUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前账号未绑定邮箱，暂不支持在线换绑",
        ) from exc
    except OtpSendRateLimitedError as exc:
        raise HTTPException(status_code=429, detail=exc.detail) from exc
    except OtpDeliveryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from exc
    return {"detail": "验证码已发送至当前账号邮箱"}


@router.post(
    "/auth/me/email-change/send-new",
    summary="发送换绑验证码到新邮箱（已登录）",
)
async def send_email_change_new_otp(
    body: SendEmailChangeNewOtpRequest,
    request: Request,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: UserAccountRepository = Depends(get_user_account_repository),
) -> dict[str, Any]:
    """始终返回同一文案：不在发送阶段暴露新邮箱是否已被其他账号占用。"""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    await _enforce_rate_limit(
        request, action="auth.send_email_change_otp", limit=_OTP_SEND_RATE_LIMIT
    )
    lifecycle = build_account_lifecycle(
        repository=repository,
        otp=_get_email_service(request),
    )
    try:
        await lifecycle.request_email_change_new_otp(
            user_id=_user_id(current_user),
            new_email=str(body.new_email),
        )
    except account_lifecycle.EmailChangeUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前账号未绑定邮箱，暂不支持在线换绑",
        ) from exc
    except account_lifecycle.EmailChangeSameEmail as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新邮箱不能与当前邮箱相同",
        ) from exc
    except OtpSendRateLimitedError as exc:
        raise HTTPException(status_code=429, detail=exc.detail) from exc
    except OtpDeliveryUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.detail) from exc
    return {"detail": "验证码已发送至新邮箱"}


@router.post("/auth/me/email-change/confirm", summary="确认换绑邮箱（双验证码）")
async def confirm_email_change(
    body: ConfirmEmailChangeRequest,
    request: Request,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: UserAccountRepository = Depends(get_user_account_repository),
    oauth_repository: Any = Depends(get_oauth_identity_repository),
) -> dict[str, Any]:
    """凭当前邮箱与新邮箱两枚验证码原子换绑，返回换绑后的权威账户投影。

    归属冲突（含并发下 users.email 唯一约束兜底）统一映射中性 409，
    不区分“验证码错”之外的失败原因，避免泄露邮箱归属。
    """
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    await _enforce_rate_limit(
        request, action="auth.email_change", limit=_AUTH_ATTEMPT_RATE_LIMIT
    )
    lifecycle = build_account_lifecycle(
        repository=repository,
        otp=_get_email_service(request),
    )
    try:
        await lifecycle.change_email(
            user_id=_user_id(current_user),
            new_email=str(body.new_email),
            current_code=body.current_code,
            new_code=body.new_code,
        )
    except account_lifecycle.EmailChangeUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前账号未绑定邮箱，暂不支持在线换绑",
        ) from exc
    except account_lifecycle.EmailChangeSameEmail as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新邮箱不能与当前邮箱相同",
        ) from exc
    except account_lifecycle.InvalidOtp as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码错误或已过期",
        ) from exc
    except account_lifecycle.EmailAlreadyInUse as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="换绑失败，请更换邮箱后重试",
        ) from exc
    except pg_errors.UniqueViolation as exc:
        # 并发换绑同一新邮箱：唯一约束兜底，口径与归属预检一致
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="换绑失败，请更换邮箱后重试",
        ) from exc
    except account_lifecycle.EmailChangeFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="邮箱换绑失败，请稍后重试",
        ) from exc
    return await _account_view(
        current_user=current_user,
        repository=repository,
        oauth_repository=oauth_repository,
    )


@router.post("/auth/register", summary="用户注册（邮箱 + 验证码 + 密码）")
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    repository: UserAccountRepository = Depends(get_user_account_repository),
) -> dict[str, Any]:
    """
    注册新用户。

    1. 校验邮箱验证码（consume=False 先不删除）
    2. 检查邮箱是否已注册
    3. bcrypt 哈希密码后写库
    4. 消耗验证码
    """
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
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
            username=body.username,
        )
    except account_lifecycle.InvalidOtp as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证码错误或已过期",
        ) from exc
    except account_lifecycle.AccountAlreadyExists as exc:
        # 保持中性文案，引导登录或找回密码，避免误导用户重复获取验证码
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="注册未完成，请尝试登录；如忘记密码，请通过“忘记密码”重置后登录",
        ) from exc
    return {"detail": "注册成功", "user_id": result.user_id}


@router.post("/auth/login", summary="登录（邮箱 + 密码）")
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    repository: UserAccountRepository = Depends(get_user_account_repository),
) -> dict[str, Any]:
    """
    用户登录，返回 JWT。

    - 查库验证邮箱 + 密码
    - 签发 JWT（payload 含 user_id、role、email）
    """
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    await _enforce_rate_limit(request, action="auth.login", limit=_AUTH_ATTEMPT_RATE_LIMIT)
    # per-账号节流：分布式 IP 对同一邮箱的爆破归并到单一账号桶；
    # 域名归一与登录生命周期同口径，防大小写变体拆桶
    account_identity = account_lifecycle._normalize_email_domain(str(body.email).strip())
    await _enforce_rate_limit(
        request,
        action="auth.login.account",
        limit=_LOGIN_ACCOUNT_RATE_LIMIT,
        identity=account_identity,
    )
    # 失败锁定：窗口内密码核验失败达上限的账号直接拒绝（含密码正确者）
    await _enforce_login_lockout(request, email=account_identity)
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
    except account_lifecycle.AccountDisabled as exc:
        # 密码已核验通过才到达此处，明示禁用不构成账号枚举
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用，请联系管理员",
        ) from exc
    except account_lifecycle.InvalidCredentials as exc:
        await _record_login_failure(request, email=account_identity)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
        ) from exc
    await _clear_login_failures(request, email=account_identity)
    return {
        "access_token": result.access_token,
        "token_type": result.token_type,
        "role": result.role,
        # 种子默认凭据登录提示：前端据此常驻提醒改密
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


# ---------------------------------------------------------------- DSH MCP token

# DSH 向导签发参数全部由服务端固定：purpose/scope/客户端标识不接受请求体
# 覆盖，客户端更不能声明 membership_tier/group——MCP 调用按 token 属主
# 在 users 表中的实时生效档位计费（Python 与 mcp-go 同口径）。
_DSH_MCP_TOKEN_SCOPES = ["projects:favorites:read"]
_DSH_MCP_TOKEN_CLIENT_TYPE = "other"
_DSH_MCP_TOKEN_CLIENT_LABEL = "dsh-aigc-radar"
# rotate 吊销旧凭证，限速防脚本化刷量（窗口与认证端点同）
_DSH_TOKEN_ROTATE_RATE_LIMIT = 5

DSH_TOKEN_RECOVERY_REQUIRED_CODE = "dsh_token_recovery_required"


def _new_dsh_mcp_token_material() -> dict[str, str]:
    """生成新 DSH MCP token 并密封明文；密钥未配置/非法时抛
    DshMcpTokenSecretError。绝不把明文落库：库里只有 SHA-256 hash
    与 AES-256-GCM 密封信封。"""
    token = "aigc_mcp_" + secrets.token_urlsafe(32)
    secret_box = build_dsh_mcp_token_secret_box()
    if secret_box is None:
        raise DshMcpTokenSecretError("dsh mcp token 加密密钥未配置")
    return {
        "token": token,
        "token_hash": hash_mcp_token(token),
        "token_hint": f"{token[:12]}...{token[-4:]}",
        "token_encrypted": json.dumps(secret_box.seal(token), ensure_ascii=False),
    }


def _dsh_mcp_token_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "token": item["token"],
        "token_metadata": item["token_metadata"],
        "reused": item.get("status") == "reused",
    }
    if "revoked_count" in item:
        payload["revoked_count"] = item["revoked_count"]
    return payload


def _dsh_repository_kwargs(user_id: int, material: dict[str, str]) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "token_hash": material["token_hash"],
        "token_hint": material["token_hint"],
        "token_encrypted": material["token_encrypted"],
        "scopes": _DSH_MCP_TOKEN_SCOPES,
        "client_type": _DSH_MCP_TOKEN_CLIENT_TYPE,
        "client_label": _DSH_MCP_TOKEN_CLIENT_LABEL,
    }


@router.post(
    "/auth/me/mcp-tokens/dsh/ensure",
    summary="确保当前用户的 DSH MCP Token（跨刷新复用同一枚）",
)
async def ensure_dsh_mcp_token(
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: DshMcpTokenManager = Depends(get_mcp_access_token_repository),
) -> dict[str, Any]:
    """每用户一个活跃 DSH token：首次签发，之后解密回显同一枚。

    历史 hash-only DSH token 无法回显明文：返回 409 +
    detail.code=dsh_token_recovery_required，由用户显式调用 rotate
    轮换，绝不静默吊销仍在使用的旧 token。
    """
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    try:
        material = _new_dsh_mcp_token_material()
        item = await asyncio.to_thread(
            repository.ensure_user_dsh_mcp_token,
            **_dsh_repository_kwargs(_user_id(current_user), material),
        )
    except DshMcpTokenSecretError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DSH token 服务未配置加密密钥",
        ) from exc
    except pg_errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="DSH token 生成冲突，请重试",
        ) from exc
    if item.get("status") == "recovery_required":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": DSH_TOKEN_RECOVERY_REQUIRED_CODE,
                "message": "旧版 DSH token 无法自动恢复，请重新生成",
            },
        )
    return _dsh_mcp_token_payload(item)


@router.post(
    "/auth/me/mcp-tokens/dsh/rotate",
    summary="重新生成 DSH MCP Token（旧 DSH token 立即吊销）",
)
async def rotate_dsh_mcp_token(
    request: Request,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: DshMcpTokenManager = Depends(get_mcp_access_token_repository),
) -> dict[str, Any]:
    """legacy 恢复与泄漏自愈入口：单事务吊销旧 DSH token 并签发新 token。"""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    await _enforce_rate_limit(
        request, action="auth.dsh_mcp_token_rotate", limit=_DSH_TOKEN_ROTATE_RATE_LIMIT
    )
    try:
        material = _new_dsh_mcp_token_material()
        item = await asyncio.to_thread(
            repository.rotate_user_dsh_mcp_token,
            **_dsh_repository_kwargs(_user_id(current_user), material),
        )
    except DshMcpTokenSecretError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DSH token 服务未配置加密密钥",
        ) from exc
    except pg_errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="DSH token 生成冲突，请重试",
        ) from exc
    return _dsh_mcp_token_payload(item)


# ---------------------------------------------------------------- RSS feed token

# 重新生成是吊销旧凭证的敏感操作，限速防脚本化刷量（窗口与上面认证端点同）
_FEED_TOKEN_ROTATE_RATE_LIMIT = 5


def _new_feed_token_material() -> dict[str, str]:
    """生成新 feed token 并密封明文；密钥未配置/非法时抛 FeedTokenSecretError。

    绝不把明文落库：库里只有 SHA-256 hash 与 AES-256-GCM 密封信封。
    """
    token = "aigc_feed_" + secrets.token_urlsafe(32)
    secret_box = build_feed_token_secret_box()
    if secret_box is None:
        raise FeedTokenSecretError("feed token 加密密钥未配置")
    return {
        "token": token,
        "token_hash": hash_feed_token(token),
        "token_hint": f"{token[:14]}...{token[-4:]}",
        "token_encrypted": json.dumps(secret_box.seal(token), ensure_ascii=False),
    }


def _feed_token_payload(item: dict[str, Any]) -> dict[str, Any]:
    """对外载荷：完整 token（供拼 RSS 链接）+ hint + 是否本次新建。不含 URL，
    前端用 window.location.origin 自行拼装（避免部署基址漂移写进库侧契约）。"""
    return {
        "token": item["token"],
        "token_hint": item["token_hint"],
        "created": bool(item.get("created")),
        "created_at": item.get("created_at"),
    }


@router.get("/auth/me/feed-token", summary="获取（或首次签发）当前用户的 RSS feed token")
async def get_feed_token(
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: FeedTokenRepository = Depends(get_feed_token_repository),
) -> dict[str, Any]:
    """每用户一个永不过期的 feed token，所有 RSS 渠道共用；重复调用返回同一枚。"""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    try:
        material = _new_feed_token_material()
        item = await asyncio.to_thread(
            repository.get_or_create_feed_token,
            user_id=_user_id(current_user),
            token_hash=material["token_hash"],
            token_hint=material["token_hint"],
            token_encrypted=material["token_encrypted"],
        )
    except FeedTokenSecretError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RSS token 服务未配置加密密钥",
        ) from exc
    return _feed_token_payload(item)


@router.post(
    "/auth/me/feed-token/rotate",
    summary="重新生成 RSS feed token（旧 token 立即吊销）",
)
async def rotate_feed_token(
    request: Request,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: FeedTokenRepository = Depends(get_feed_token_repository),
) -> dict[str, Any]:
    """泄漏自愈入口：单事务吊销旧 token 并签发新 token，旧 RSS 链接即刻失效。"""
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    await _enforce_rate_limit(
        request, action="auth.feed_token_rotate", limit=_FEED_TOKEN_ROTATE_RATE_LIMIT
    )
    try:
        material = _new_feed_token_material()
        item = await asyncio.to_thread(
            repository.rotate_feed_token,
            user_id=_user_id(current_user),
            token_hash=material["token_hash"],
            token_hint=material["token_hint"],
            token_encrypted=material["token_encrypted"],
        )
    except FeedTokenSecretError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RSS token 服务未配置加密密钥",
        ) from exc
    except pg_errors.UniqueViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="RSS token 生成冲突，请重试",
        ) from exc
    return _feed_token_payload(item)


async def _account_view(
    *,
    current_user: dict[str, Any],
    repository: UserAccountRepository,
    oauth_repository: Any,
) -> dict[str, Any]:
    """Build the public account projection exclusively from current DB rows."""
    user_id = _user_id(current_user)
    record = await asyncio.to_thread(repository.get_user_by_id, user_id)
    if record is None:
        raise HTTPException(status_code=401, detail="用户身份无效")
    identities = await asyncio.to_thread(
        oauth_repository.list_identities_for_user, user_id
    )
    change_required = await asyncio.to_thread(
        password_change_required_for_email,
        repository=repository,
        email=str(record.get("email") or ""),
        configured_email=settings.DEFAULT_ADMIN_EMAIL,
        configured_password=settings.DEFAULT_ADMIN_PASSWORD,
        verify_password=verify_password,
    )
    # 会员展示口径与 RequireUser 身份同构（0048）：库内档位列不回写，
    # 生效档位按 resolve_effective_tier 收口（member 过期按 free，未知值
    # fail-closed 归 free）；expires_at 原样透传供读取侧展示与前端二次判定。
    expires_at = record.get("membership_expires_at")
    return {
        "user_id": user_id,
        "email": record.get("email"),
        "username": record.get("username"),
        "avatar_url": (
            f"/api/auth/avatars/{user_id}/{record['avatar_digest']}.png"
            if record.get("avatar_digest") else None
        ),
        "email_verified": bool(record.get("email_verified", False)),
        "role": record.get("role"),
        "membership_tier": resolve_effective_tier(
            record.get("membership_tier"), expires_at
        ),
        "membership_expires_at": (
            expires_at.isoformat() if hasattr(expires_at, "isoformat") else None
        ),
        "created_at": record.get("created_at"),
        "password_login_enabled": bool(record.get("password_login_enabled", False)),
        "password_change_required": change_required,
        "oauth_identities": identities,
    }


@router.patch("/auth/me/profile", summary="修改当前用户资料")
async def update_profile(
    body: UpdateProfileRequest,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: UserAccountRepository = Depends(get_user_account_repository),
    oauth_repository: Any = Depends(get_oauth_identity_repository),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    lifecycle = build_account_lifecycle(
        repository=repository,
        password_hasher=hash_password,
        password_verifier=verify_password,
    )
    try:
        await lifecycle.update_username(
            user_id=_user_id(current_user), username=body.username
        )
    except account_lifecycle.ProfileUpdateFailed as exc:
        raise HTTPException(status_code=500, detail="资料修改失败，请稍后重试") from exc
    return await _account_view(
        current_user=current_user,
        repository=repository,
        oauth_repository=oauth_repository,
    )


@router.get("/auth/me", summary="获取当前登录用户信息")
async def me(
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: UserAccountRepository = Depends(get_user_account_repository),
    oauth_repository: Any = Depends(get_oauth_identity_repository),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return await _account_view(
        current_user=current_user,
        repository=repository,
        oauth_repository=oauth_repository,
    )


@router.post("/auth/me/avatar", summary="上传当前用户头像")
async def upload_avatar(
    request: Request,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    file: UploadFile = File(...),
    repository: UserAccountRepository = Depends(get_user_account_repository),
    oauth_repository: Any = Depends(get_oauth_identity_repository),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    user_id = _user_id(current_user)
    await _enforce_rate_limit(request, action="avatar_upload", limit=10, identity=str(user_id))
    try:
        payload = await file.read(MAX_AVATAR_BYTES + 1)
    finally:
        await file.close()
    if len(payload) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=413, detail="头像不能超过 2 MB")
    try:
        png = await asyncio.to_thread(normalize_avatar, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    digest = hashlib.sha256(png).hexdigest()
    updated = await asyncio.to_thread(
        repository.update_user_avatar, user_id=user_id, png=png, digest=digest
    )
    if updated != 1:
        raise HTTPException(status_code=401, detail="用户身份无效")
    return await _account_view(
        current_user=current_user, repository=repository, oauth_repository=oauth_repository
    )


@router.get("/auth/avatars/{user_id}/{digest}.png", summary="读取用户头像")
async def avatar_image(
    user_id: int,
    digest: str,
    repository: UserAccountRepository = Depends(get_user_account_repository),
) -> Response:
    if user_id < 1 or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise HTTPException(status_code=404, detail="头像不存在")
    png = await asyncio.to_thread(repository.get_user_avatar, user_id=user_id, digest=digest)
    if png is None:
        raise HTTPException(status_code=404, detail="头像不存在")
    return Response(png, media_type="image/png", headers={
        "Cache-Control": "public, max-age=3600",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    })
