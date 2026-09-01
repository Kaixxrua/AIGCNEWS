"""One-time, opaque OAuth callback handoff stored in Redis."""

from __future__ import annotations

import secrets
from typing import Any

from backend.app.models.schema_oauth import OAuthBindHandoffPayload, OAuthHandoffPayload
from backend.app.services.auth.oauth.state import digest_secret

OAUTH_HANDOFF_PREFIX = "auth:oauth:handoff:"
# 绑定操作使用独立的 Redis 键空间与独立 cookie：登录 handoff 永远无法被
# 绑定 consume 读取（键不同 + 载荷模型不同），构成传输层双向隔离。
OAUTH_BIND_HANDOFF_PREFIX = "auth:oauth:bind:handoff:"


class OAuthHandoffUnavailableError(RuntimeError):
    """Redis is unavailable, so OAuth handoff cannot be issued."""


class OAuthHandoffInvalidError(ValueError):
    """Handoff is missing, expired, malformed, or already consumed."""


def handoff_key(token: str, *, prefix: str = OAUTH_HANDOFF_PREFIX) -> str:
    return f"{prefix}{digest_secret(token)}"


class OAuthHandoffStore:
    """Opaque one-time handoff store.

    model 参数化载荷类型：登录流为 OAuthHandoffPayload，绑定流为
    OAuthBindHandoffPayload；consume 时按存储侧模型校验，跨操作的重放
    在模型层即被拒绝。
    """

    def __init__(
        self,
        redis_client: Any,
        *,
        ttl_seconds: int = 120,
        prefix: str = OAUTH_HANDOFF_PREFIX,
        model: type[OAuthHandoffPayload] | type[OAuthBindHandoffPayload] = OAuthHandoffPayload,
    ) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds
        self._prefix = prefix
        self._model = model

    @property
    def available(self) -> bool:
        return self._redis is not None

    async def put(self, payload: OAuthHandoffPayload | OAuthBindHandoffPayload) -> str:
        if not self.available:
            raise OAuthHandoffUnavailableError
        token = secrets.token_urlsafe(32)
        await self._redis.set(
            handoff_key(token, prefix=self._prefix),
            payload.model_dump_json(),
            ex=self._ttl_seconds,
        )
        return token

    async def consume(self, token: str) -> OAuthHandoffPayload | OAuthBindHandoffPayload:
        if not self.available:
            raise OAuthHandoffUnavailableError
        if not token or len(token) > 512:
            raise OAuthHandoffInvalidError
        value = await self._getdel(handoff_key(token, prefix=self._prefix))
        if value is None:
            raise OAuthHandoffInvalidError
        try:
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            return self._model.model_validate_json(value)
        except (UnicodeDecodeError, TypeError, ValueError) as exc:
            raise OAuthHandoffInvalidError from exc

    async def _getdel(self, key: str) -> Any:
        getdel = getattr(self._redis, "getdel", None)
        if getdel is not None:
            return await getdel(key)
        return await self._redis.eval(
            "local value = redis.call('GET', KEYS[1]); "
            "if value then redis.call('DEL', KEYS[1]); end; return value",
            1,
            key,
        )
