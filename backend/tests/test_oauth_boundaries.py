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


def test_state_payload_operation_contract() -> None:
    from pydantic import ValidationError

    from backend.app.models.schema_oauth import OAuthBindHandoffPayload

    base = dict(
        provider="github",
        redirect_to="/",
        browser_binding_hash="a" * 64,
    )
    # 默认 login 不可携带目标账户；bind 必须携带正整数目标账户
    OAuthStatePayload(**base)
    with pytest.raises(ValidationError):
        OAuthStatePayload(**base, target_user_id=7)
    with pytest.raises(ValidationError):
        OAuthStatePayload(**base, operation="bind")
    with pytest.raises(ValidationError):
        OAuthStatePayload(**base, operation="bind", target_user_id=0)
    bound = OAuthStatePayload(**base, operation="bind", target_user_id=7)
    assert bound.operation == "bind" and bound.target_user_id == 7

    # 绑定 handoff 载荷同样拒绝非正目标账户
    with pytest.raises(ValidationError):
        OAuthBindHandoffPayload(
            user_id=0,
            provider="github",
            status="bound",
            redirect_to="/",
            browser_binding_hash="a" * 64,
        )


def test_bind_state_store_uses_isolated_namespace() -> None:
    import asyncio

    from backend.app.services.auth.oauth.state import OAUTH_BIND_STATE_PREFIX

    redis = FakeRedis()
    bind_store = OAuthStateStore(redis, ttl_seconds=77, prefix=OAUTH_BIND_STATE_PREFIX)
    login_store = OAuthStateStore(redis, ttl_seconds=77)
    material = create_state_material(use_pkce=True, use_nonce=False)
    payload = OAuthStatePayload(
        provider="github",
        redirect_to="/",
        pkce_verifier=material.code_verifier,
        browser_binding_hash=digest_secret(material.browser_binding),
        operation="bind",
        target_user_id=7,
    )

    asyncio.run(bind_store.put(material, payload))
    bind_key = state_key(material.state, prefix=OAUTH_BIND_STATE_PREFIX)
    assert bind_key in redis.values
    assert state_key(material.state) not in redis.values
    # 登录空间消费不到绑定 state（键空间隔离）
    with pytest.raises(ValueError):
        asyncio.run(login_store.consume(material.state))
    assert asyncio.run(bind_store.consume(material.state)) == payload


def test_bind_handoff_store_isolated_and_model_pinned() -> None:
    import asyncio

    from backend.app.models.schema_oauth import OAuthBindHandoffPayload
    from backend.app.services.auth.oauth.handoff import (
        OAUTH_BIND_HANDOFF_PREFIX,
        handoff_key,
    )

    redis = FakeRedis()
    bind_store = OAuthHandoffStore(
        redis,
        ttl_seconds=55,
        prefix=OAUTH_BIND_HANDOFF_PREFIX,
        model=OAuthBindHandoffPayload,
    )
    login_store = OAuthHandoffStore(redis, ttl_seconds=55)
    payload = OAuthBindHandoffPayload(
        user_id=7,
        provider="github",
        status="bound",
        redirect_to="/",
        browser_binding_hash="a" * 64,
    )

    token = asyncio.run(bind_store.put(payload))
    assert handoff_key(token, prefix=OAUTH_BIND_HANDOFF_PREFIX) in redis.values
    assert handoff_key(token) not in redis.values
    # 登录空间消费不到绑定 handoff
    with pytest.raises(ValueError):
        asyncio.run(login_store.consume(token))
    assert asyncio.run(bind_store.consume(token)) == payload

    # 跨操作重放：登录模型载荷即使塞进绑定键，也在模型层被拒
    foreign = OAuthHandoffPayload(
        user_id=7, redirect_to="/", browser_binding_hash="a" * 64
    )
    redis.values[handoff_key("foreign", prefix=OAUTH_BIND_HANDOFF_PREFIX)] = (
        foreign.model_dump_json()
    )
    with pytest.raises(ValueError):
        asyncio.run(bind_store.consume("foreign"))
