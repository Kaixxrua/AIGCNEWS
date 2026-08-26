from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from backend.app.core.config import settings
from backend.app.repositories.user_account_repository import UserAccountReader
from backend.app.services.membership.tiers import resolve_effective_tier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Password hashing（使用 bcrypt 官方库，不依赖 passlib）
# ---------------------------------------------------------------------------


def hash_password(plain: str) -> str:
    """使用 bcrypt 对明文密码进行哈希。"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文密码与哈希是否匹配。"""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


# ---------------------------------------------------------------------------
# JWT utilities
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)

# 历史上随仓库公开的示例密钥：任何出现在此集合中的值都必须视为已泄漏。
KNOWN_INSECURE_JWT_SECRETS: frozenset[str] = frozenset(
    {
        "change-me-in-production",
        "change-me-in-production-use-a-long-random-string",
    }
)

MIN_JWT_SECRET_LENGTH = 32


def validate_jwt_secret(secret: str) -> None:
    """Fail fast when the JWT signing secret is missing, leaked, or too weak.

    使用公开默认密钥意味着任何人都能离线伪造 admin token，因此必须拒绝启动。
    """
    if not secret or secret in KNOWN_INSECURE_JWT_SECRETS:
        raise RuntimeError(
            "JWT_SECRET_KEY 未配置或仍为公开的示例值，拒绝启动。"
            "请使用 `openssl rand -hex 32` 生成强随机密钥并写入 .env。"
        )
    if len(secret) < MIN_JWT_SECRET_LENGTH:
        raise RuntimeError(
            f"JWT_SECRET_KEY 长度不足 {MIN_JWT_SECRET_LENGTH} 字符，拒绝启动。"
            "请使用 `openssl rand -hex 32` 生成强随机密钥并写入 .env。"
        )


def create_access_token(data: dict[str, Any]) -> str:
    """生成 JWT，过期时间 = 当前时间 + ACCESS_TOKEN_EXPIRE_MINUTES。"""
    payload = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload["exp"] = expire
    return jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    """解析 JWT，失败时抛出 HTTP 401。"""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload  # type: ignore[return-value]
    except JWTError as exc:
        logger.warning("[Auth] JWT decode failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ---------------------------------------------------------------------------
# FastAPI Dependencies
# ---------------------------------------------------------------------------


def get_user_identity_repository(request: Request) -> UserAccountReader | None:
    """Return the user account repository only when Bearer authentication is attempted."""
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        return None

    repositories = getattr(request.app.state, "application_repositories", None)
    if repositories is None:
        raise RuntimeError("Application repositories are not configured")
    return repositories.users


async def RequireUser(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    repository: UserAccountReader | None = Depends(get_user_identity_repository),
) -> dict[str, Any]:
    """FastAPI 依赖：要求请求携带有效 Bearer JWT，并以库内状态为准核验身份。

    JWT 解码成功后按主键查询用户表（每请求一次，不加缓存，避免角色陈旧窗口）：

    - 账号不存在或已禁用 → 401，删除/禁用立即生效，解决 token 无法服务端撤销的问题；
    - 返回身份的 role 一律以数据库为准，token 内 role 仅为签发时快照，
      管理员降级在下一个请求即生效（RequireAdmin 随之拒绝）。
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 Authorization 头",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(credentials.credentials)
    user_id = extract_user_id(payload)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户身份无效",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if repository is None:
        # 携带 Bearer 头时 get_user_identity_repository 必然返回仓储或抛错，
        # 此分支仅防御仓储依赖被异常覆盖的场景。
        raise RuntimeError("User account repository is not configured")
    record = await asyncio.to_thread(repository.get_user_by_id, user_id)
    if record is None or record.get("disabled"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号不存在或已被禁用",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # 口令版本比对：改密会递增库内 pwd_ver，签发时写入 JWT 的声明随之失配，
    # 旧 token 在下一个请求即失效（改密即撤销）。库内缺列（迁移未应用）时
    # 跳过比对保持兼容；token 缺声明（升级前签发的历史 JWT）一律按失效处理。
    record_pwd_ver = record.get("pwd_ver")
    if record_pwd_ver is not None and payload.get("pwd_ver") != record_pwd_ver:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录状态已失效，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    identity = dict(payload)
    identity["role"] = record.get("role") or "user"
    # 会员档位以库内为准（0045），授予/吊销下一个请求即生效；
    # 库内缺列（迁移未应用）时回退 free，与 pwd_ver 缺列跳过同属热重启兼容口径。
    # 到期语义（0048）：member 过期的生效档位按 free，expires_at 原样透传供
    # /auth/me 等读取侧展示；库内缺列时 .get → None（长期有效）。
    identity["membership_tier"] = resolve_effective_tier(
        record.get("membership_tier"),
        record.get("membership_expires_at"),
    )
    expires_at = record.get("membership_expires_at")
    identity["membership_expires_at"] = (
        expires_at.isoformat() if hasattr(expires_at, "isoformat") else None
    )
    return identity


async def OptionalUser(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any] | None:
    """FastAPI 依赖：可选登录态；缺失或无效 token 都按匿名访问处理。"""
    if credentials is None:
        return None
    try:
        return decode_access_token(credentials.credentials)
    except HTTPException:
        return None


def extract_user_id(identity: Mapping[str, Any] | None) -> int | None:
    """从 JWT payload / 身份映射中提取正整数 user_id，非法值一律返回 None。

    路由层与服务层共享同一提取规则（user_id → id → sub 依次回退），
    避免各调用点各自解析导致口径漂移。
    """
    if not isinstance(identity, Mapping):
        return None
    raw = identity.get("user_id") or identity.get("id") or identity.get("sub")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def hash_mcp_token(token: str) -> str:
    """Return the stable SHA-256 digest stored for an inbound MCP token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_feed_token(token: str) -> str:
    """Return the stable SHA-256 digest stored for a member RSS feed token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_mcp_access_token_authenticator(request: Request):
    """Return the token repository only when Bearer authentication is attempted."""
    authorization = request.headers.get("authorization", "")
    if not authorization.lower().startswith("bearer "):
        return None

    repositories = getattr(request.app.state, "application_repositories", None)
    if repositories is None:
        raise RuntimeError("Application repositories are not configured")
    return repositories.mcp_access_tokens


async def OptionalMcpUser(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    repository=Depends(get_mcp_access_token_authenticator),
) -> dict[str, Any] | None:
    """Authenticate an optional inbound MCP token; reject every supplied invalid auth header."""
    authorization = request.headers.get("authorization")
    if authorization and credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization 必须使用 Bearer Token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if credentials is None:
        return None
    user = await asyncio.to_thread(
        repository.get_user_by_mcp_token_hash,
        hash_mcp_token(credentials.credentials),
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MCP Token 无效、已过期或已撤销",
            headers={"WWW-Authenticate": "Bearer"},
        )
    scopes = user.get("scopes")
    if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MCP Token 权限无效",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user["scopes"] = frozenset(scopes)
    return user


async def RequireAdmin(
    user: dict[str, Any] = Depends(RequireUser),
) -> dict[str, Any]:
    """FastAPI 依赖：要求当前用户角色为 admin，否则抛出 HTTP 403。"""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足，需要管理员角色",
        )
    return user
