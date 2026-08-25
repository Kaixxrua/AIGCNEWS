"""One-time, opaque OAuth callback handoff stored in Redis."""

from __future__ import annotations

import secrets
from typing import Any

from backend.app.models.schema_oauth import OAuthHandoffPayload
from backend.app.services.auth.oauth.state import digest_secret

OAUTH_HANDOFF_PREFIX = "auth:oauth:handoff:"


class OAuthHandoffUnavailableError(RuntimeError):
    """Redis is unavailable, so OAuth handoff cannot be issued."""


class OAuthHandoffInvalidError(ValueError):
    """Handoff is missing, expired, malformed, or already consumed."""


def handoff_key(token: str) -> str:
    return f"{OAUTH_HANDOFF_PREFIX}{digest_secret(token)}"


class OAuthHandoffStore:
    def __init__(self, redis_client: Any, *, ttl_seconds: int = 120) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    @property
    def available(self) -> bool:
        return self._redis is not None

    async def put(self, payload: OAuthHandoffPayload) -> str:
        if not self.available:
            raise OAuthHandoffUnavailableError
        token = secrets.token_urlsafe(32)
        await self._redis.set(
            handoff_key(token), payload.model_dump_json(), ex=self._ttl_seconds
        )
        return token

    async def consume(self, token: str) -> OAuthHandoffPayload:
        if not self.available:
            raise OAuthHandoffUnavailableError
        if not token or len(token) > 512:
            raise OAuthHandoffInvalidError
        value = await self._getdel(handoff_key(token))
        if value is None:
            raise OAuthHandoffInvalidError
        try:
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            return OAuthHandoffPayload.model_validate_json(value)
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
