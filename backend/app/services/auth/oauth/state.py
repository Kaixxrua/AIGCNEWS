"""One-time OAuth state and PKCE material backed by the application Redis client."""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any

from backend.app.models.schema_oauth import OAuthStatePayload

OAUTH_STATE_PREFIX = "auth:oauth:state:"


class OAuthStateUnavailableError(RuntimeError):
    """Redis is unavailable, so OAuth must fail closed."""


class OAuthStateInvalidError(ValueError):
    """State is missing, expired, malformed, or already consumed."""


@dataclass(frozen=True, slots=True)
class OAuthStateMaterial:
    state: str
    code_verifier: str | None
    nonce: str | None
    browser_binding: str


def digest_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def state_key(state: str) -> str:
    return f"{OAUTH_STATE_PREFIX}{digest_secret(state)}"


def create_state_material(*, use_pkce: bool, use_nonce: bool) -> OAuthStateMaterial:
    return OAuthStateMaterial(
        state=secrets.token_urlsafe(32),
        code_verifier=secrets.token_urlsafe(64) if use_pkce else None,
        nonce=secrets.token_urlsafe(32) if use_nonce else None,
        browser_binding=secrets.token_urlsafe(32),
    )


class OAuthStateStore:
    def __init__(self, redis_client: Any, *, ttl_seconds: int = 300) -> None:
        self._redis = redis_client
        self._ttl_seconds = ttl_seconds

    @property
    def available(self) -> bool:
        return self._redis is not None

    async def put(self, material: OAuthStateMaterial, payload: OAuthStatePayload) -> None:
        if not self.available:
            raise OAuthStateUnavailableError
        value = payload.model_dump_json()
        await self._redis.set(state_key(material.state), value, ex=self._ttl_seconds)

    async def consume(self, state: str) -> OAuthStatePayload:
        if not self.available:
            raise OAuthStateUnavailableError
        if not state or len(state) > 512:
            raise OAuthStateInvalidError
        value = await self._getdel(state_key(state))
        if value is None:
            raise OAuthStateInvalidError
        try:
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            return OAuthStatePayload.model_validate_json(value)
        except (UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OAuthStateInvalidError from exc

    async def _getdel(self, key: str) -> Any:
        getdel = getattr(self._redis, "getdel", None)
        if getdel is not None:
            return await getdel(key)
        # Redis versions without GETDEL still get atomic one-time semantics via
        # a Lua script executed server-side, rather than a racy GET then DEL.
        return await self._redis.eval(
            "local value = redis.call('GET', KEYS[1]); "
            "if value then redis.call('DEL', KEYS[1]); end; return value",
            1,
            key,
        )
