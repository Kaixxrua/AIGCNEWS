from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.app.models.schema_oauth import OAuthHandoffPayload, OAuthStatePayload
from backend.app.services.auth.oauth.handoff import OAuthHandoffStore
from backend.app.services.auth.oauth.redirect import OAuthRedirectError, safe_internal_redirect
from backend.app.services.auth.oauth.state import (
    OAuthStateStore,
    create_state_material,
    digest_secret,
    state_key,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.getdel = AsyncMock(side_effect=self._getdel)
        self.eval = AsyncMock()

    async def _getdel(self, key: str):
        return self.values.pop(key, None)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.ttls[key] = ex


@pytest.mark.parametrize("value", ["https://evil.example", "//evil.example", "evil", "/\\evil", "/%2f%2fevil", "/%5cevil", "/ok\n"])
def test_internal_redirect_rejects_external_and_parser_bypasses(value: str) -> None:
    with pytest.raises(OAuthRedirectError):
        safe_internal_redirect(value)


def test_internal_redirect_preserves_query_without_fragment() -> None:
    assert safe_internal_redirect("/settings?tab=oauth") == "/settings?tab=oauth"


def test_state_store_hashes_key_and_consumes_once() -> None:
    redis = FakeRedis()
    store = OAuthStateStore(redis, ttl_seconds=77)
    material = create_state_material(use_pkce=True, use_nonce=True)
    payload = OAuthStatePayload(
        provider="google",
        redirect_to="/",
        pkce_verifier=material.code_verifier,
        nonce=material.nonce,
        browser_binding_hash=digest_secret(material.browser_binding),
    )

    import asyncio
    asyncio.run(store.put(material, payload))
    assert state_key(material.state) in redis.values
    assert material.state not in redis.values
    assert redis.ttls[state_key(material.state)] == 77
    assert asyncio.run(store.consume(material.state)) == payload
    with pytest.raises(ValueError):
        asyncio.run(store.consume(material.state))


def test_handoff_store_is_opaque_and_one_time() -> None:
    redis = FakeRedis()
    store = OAuthHandoffStore(redis, ttl_seconds=55)
    payload = OAuthHandoffPayload(user_id=42, redirect_to="/", browser_binding_hash="a" * 64)

    import asyncio
    token = asyncio.run(store.put(payload))
    assert token not in redis.values
    assert asyncio.run(store.consume(token)) == payload
    with pytest.raises(ValueError):
        asyncio.run(store.consume(token))
