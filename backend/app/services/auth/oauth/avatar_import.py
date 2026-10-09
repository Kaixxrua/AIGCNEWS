"""第三方首登头像导入：登录响应发出后尽力而为地拉取 provider 头像。

provider 返回的头像 URL 不可信：只接受已知 provider 头像域名的 https 地址、
不跟随重定向、限时限量读取，并经 normalize_avatar 重编码后才落库；且只写入
尚无头像的账户。任何失败只记日志，绝不影响已完成的登录。
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from backend.app.repositories.user_account_repository import UserAccountRepository
from backend.app.services.auth.avatar import MAX_AVATAR_BYTES, normalize_avatar

logger = logging.getLogger(__name__)
_TIMEOUT = httpx.Timeout(8.0, connect=5.0)
_EXACT_HOSTS = frozenset({"avatars.githubusercontent.com", "q.qlogo.cn", "thirdqq.qlogo.cn", "linux.do"})
_HOST_SUFFIXES = (".googleusercontent.com",)


def provider_avatar_url_allowed(url: str | None) -> bool:
    if not url or len(url) > 2048 or any(ord(char) < 0x21 for char in url):
        return False
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        port = parsed.port
    except ValueError:
        return False
    return bool(
        parsed.scheme == "https"
        and port is None
        and not parsed.username
        and not parsed.password
        and (host in _EXACT_HOSTS or any(host.endswith(suffix) for suffix in _HOST_SUFFIXES))
    )


async def fetch_provider_avatar(
    url: str,
    *,
    client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
) -> bytes | None:
    if not provider_avatar_url_allowed(url):
        return None
    async with client_factory(timeout=_TIMEOUT, follow_redirects=False) as client:
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                return None
            payload = bytearray()
            async for chunk in response.aiter_bytes():
                payload.extend(chunk)
                if len(payload) > MAX_AVATAR_BYTES:
                    return None
            return bytes(payload)


async def import_provider_avatar(
    *,
    user_id: int,
    url: str,
    users: UserAccountRepository,
    client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
) -> bool:
    """返回是否写入了头像；从不抛出。"""
    try:
        payload = await fetch_provider_avatar(url, client_factory=client_factory)
        if not payload:
            return False
        png = await asyncio.to_thread(normalize_avatar, payload)
        digest = hashlib.sha256(png).hexdigest()
        updated = await asyncio.to_thread(
            users.set_initial_user_avatar, user_id=int(user_id), png=png, digest=digest
        )
        return updated == 1
    except Exception as exc:  # noqa: BLE001 - 登录已完成，头像导入只能尽力而为
        logger.warning(
            "OAuth avatar import skipped: user_id=%s reason=%s",
            user_id, type(exc).__name__,
        )
        return False
