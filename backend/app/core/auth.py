from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from backend.app.core.config import settings

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


async def RequireUser(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict[str, Any]:
    """FastAPI 依赖：要求请求携带有效 Bearer JWT，返回 payload dict。"""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 Authorization 头",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return decode_access_token(credentials.credentials)


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


def hash_mcp_token(token: str) -> str:
    """Return the stable SHA-256 digest stored for an inbound MCP token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def OptionalMcpUser(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
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
    from backend.app.repositories.mysql_repo import MySQLRepository

    user = await asyncio.to_thread(
        MySQLRepository().get_user_by_mcp_token_hash,
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
