"""OAuth 账户绑定（bind）与登录（login）四-layer 隔离的契约测试。"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_oauth
from backend.app.api.dependencies import (
    get_oauth_identity_repository,
    get_user_account_repository,
)
from backend.app.core.auth import create_access_token, get_user_identity_repository
from backend.app.models.schema_oauth import (
    OAuthBindHandoffPayload,
    OAuthHandoffPayload,
    OAuthStatePayload,
)
from backend.app.repositories.oauth_identity_repository import OAuthBindResult
from backend.app.services.auth.oauth.contracts import OAuthProfile
from backend.app.services.auth.oauth.handoff import (
    OAUTH_BIND_HANDOFF_PREFIX,
    OAuthHandoffStore,
)
from backend.app.services.auth.oauth.runtime_config import EffectiveOAuthConfig
from backend.app.services.auth.oauth.state import (
    OAUTH_BIND_STATE_PREFIX,
    OAuthStateStore,
    create_state_material,
    digest_secret,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value

    async def getdel(self, key: str):
        return self.values.pop(key, None)


class FakeUsers:
    def __init__(self, user: dict[str, Any] | None) -> None:
        self.user = user

    def get_user_by_id(self, user_id: int):
        return self.user


class FakeIdentities:
    """记录调用轨迹的 OAuth 身份仓储；bind 结果可配置。"""

    def __init__(self, *, bind_status: str = "bound") -> None:
        self.bind_status = bind_status
        self.bind_calls: list[dict[str, Any]] = []
        self.resolve_calls: list[dict[str, Any]] = []

    def bind_identity(self, **kwargs: Any) -> OAuthBindResult:
        self.bind_calls.append(kwargs)
        return OAuthBindResult(status=self.bind_status)  # type: ignore[arg-type]

    def resolve_first_login(self, **kwargs: Any):
        self.resolve_calls.append(kwargs)
        return type(
            "Resolution",
            (),
            {"status": "authenticated", "user": {"id": 7, "role": "user", "pwd_ver": 1}},
        )()

    def list_identities_for_user(self, user_id: int) -> list[dict[str, Any]]:
        return []


class FakeAdapter:
    use_pkce = True
    use_nonce = False

    def __init__(self, *, subject: str = "gh-42") -> None:
        self.subject = subject
        self.exchange_calls: list[dict[str, Any]] = []

    def authorization_url(
        self,
        *,
        state: str,
        redirect_uri: str,
        code_challenge: str | None = None,
        nonce: str | None = None,
    ) -> str:
        return f"https://provider.test/authorize?state={state}&redirect_uri={redirect_uri}"

    async def exchange_code(self, **kwargs: Any) -> OAuthProfile:
        self.exchange_calls.append(kwargs)
        return OAuthProfile(
            provider_subject=self.subject,
            email="gh@example.test",
            email_verified=True,
            username="ghuser",
        )


USER = {"id": 7, "role": "user", "email": "u@example.test", "pwd_ver": 1}


def _config() -> EffectiveOAuthConfig:
    return EffectiveOAuthConfig(
        enabled_providers=(),
        public_base_url="https://example.test",
        github_client_id="",
        github_client_secret="",
        google_client_id="",
        google_client_secret="",
        wechat_app_id="",
        wechat_app_secret="",
        state_ttl_seconds=300,
        handoff_ttl_seconds=120,
        source="unconfigured",
    )


def _bearer(user_id: int = 7) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {create_access_token({'user_id': user_id, 'role': 'user', 'pwd_ver': 1})}"
    }


@pytest.fixture()
def rig(monkeypatch: pytest.MonkeyPatch):
    users = FakeUsers(dict(USER))
    identities = FakeIdentities()
    adapter = FakeAdapter()
    app = FastAPI()
    redis = FakeRedis()
    app.state.redis = redis
    app.include_router(routes_oauth.router, prefix="/api")
    app.dependency_overrides[get_user_account_repository] = lambda: users
    app.dependency_overrides[get_oauth_identity_repository] = lambda: identities
    app.dependency_overrides[get_user_identity_repository] = lambda: users
    monkeypatch.setattr(routes_oauth, "_config", lambda request: _config())
    monkeypatch.setattr(
        routes_oauth, "configured_oauth_providers", lambda **kwargs: ["github"]
    )
    monkeypatch.setattr(
        routes_oauth, "build_oauth_adapters", lambda config: {"github": adapter}
    )
    client = TestClient(app, base_url="https://example.test")
    return client, redis, users, identities, adapter


def _seed_state(
    redis: FakeRedis,
    *,
    bind: bool,
    browser: str = "browser-token",
    target_user_id: int | None = 7,
    provider: str = "github",
    namespace_override: str | None = None,
) -> str:
    """按真实路径播种 state；namespace_override 用于构造跨命名空间异物。"""
    material = create_state_material(use_pkce=True, use_nonce=False)
    payload_kwargs: dict[str, Any] = {
        "provider": provider,
        "redirect_to": "/settings?tab=oauth",
        "pkce_verifier": material.code_verifier,
        "nonce": material.nonce,
        "browser_binding_hash": digest_secret(browser),
    }
    if bind:
        payload_kwargs["operation"] = "bind"
        payload_kwargs["target_user_id"] = target_user_id
    prefix = namespace_override or (
        OAUTH_BIND_STATE_PREFIX if bind else "auth:oauth:state:"
    )
    store = OAuthStateStore(redis, ttl_seconds=300, prefix=prefix)
    asyncio.run(store.put(material, OAuthStatePayload(**payload_kwargs)))
    return material.state


def _seed_bind_handoff(
    redis: FakeRedis,
    *,
    browser: str = "browser-token",
    user_id: int = 7,
    status: str = "bound",
) -> str:
    store = OAuthHandoffStore(
        redis,
        ttl_seconds=120,
        prefix=OAUTH_BIND_HANDOFF_PREFIX,
        model=OAuthBindHandoffPayload,
    )
    return asyncio.run(
        store.put(
            OAuthBindHandoffPayload(
                user_id=user_id,
                provider="github",
                status=status,  # type: ignore[arg-type]
                redirect_to="/settings?tab=oauth",
                browser_binding_hash=digest_secret(browser),
            )
        )
    )


def _seed_login_handoff(
    redis: FakeRedis, *, browser: str = "browser-token", user_id: int = 7
) -> str:
    store = OAuthHandoffStore(redis, ttl_seconds=120)
    return asyncio.run(
        store.put(
            OAuthHandoffPayload(
                user_id=user_id,
                redirect_to="/settings?tab=oauth",
                browser_binding_hash=digest_secret(browser),
            )
        )
    )


# ---------------------------------------------------------------------------
# bind/start
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_bind_start_requires_authentication(rig, method) -> None:
    client, redis, *_ = rig

    response = client.request(method, "/api/auth/oauth/github/bind/start", follow_redirects=False)

    assert response.status_code == 401
    assert redis.values == {}


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_bind_start_stores_bind_namespaced_state_and_authorization_url(rig, method) -> None:
    client, redis, *_ = rig
    headers = _bearer()

    response = client.request(
        method,
        "/api/auth/oauth/github/bind/start",
        params={"redirect_to": "/projects?source=all", "target_user_id": 99},
        headers=headers,
        follow_redirects=False,
    )

    if method == "POST":
        assert response.status_code == 200
        assert set(response.json()) == {"authorization_url"}
        assert "location" not in response.headers
        assert response.headers["cache-control"] == "no-store"
        location = response.json()["authorization_url"]
    else:
        assert response.status_code == 307
        location = response.headers["location"]
    assert location.startswith("https://provider.test/authorize?state=")
    assert headers["Authorization"].removeprefix("Bearer ") not in location
    assert "target_user_id" not in location
    # provider 控制台无需新增 redirect URI：与登录共用同一回调地址
    assert "redirect_uri=https://example.test/api/auth/oauth/github/callback" in location
    bind_keys = [k for k in redis.values if k.startswith(OAUTH_BIND_STATE_PREFIX)]
    assert len(bind_keys) == 1
    assert not [k for k in redis.values if k.startswith("auth:oauth:state:")]
    payload = json.loads(redis.values[bind_keys[0]])
    assert payload["operation"] == "bind"
    assert payload["target_user_id"] == 7
    assert payload["provider"] == "github"
    assert payload["redirect_to"] == "/projects?source=all"
    assert payload["browser_binding_hash"] == digest_secret(client.cookies["aigc_oauth_browser"])
    assert "aigc_oauth_browser=" in response.headers["set-cookie"]
    for flag in ("HttpOnly", "Secure", "SameSite=lax"):
        assert flag in response.headers["set-cookie"]


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_bind_start_unavailable_provider_fails_closed(rig, monkeypatch, method) -> None:
    client, redis, *_ = rig
    monkeypatch.setattr(
        routes_oauth, "configured_oauth_providers", lambda **kwargs: []
    )

    response = client.request(
        method,
        "/api/auth/oauth/github/bind/start",
        headers=_bearer(),
        follow_redirects=False,
    )

    assert response.status_code == 503
    assert redis.values == {}


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("account_change", [{"disabled": True}, {"pwd_ver": 2}])
def test_bind_start_rejects_disabled_or_revoked_sessions(rig, method, account_change) -> None:
    client, redis, users, *_ = rig
    users.user.update(account_change)
    response = client.request(method, "/api/auth/oauth/github/bind/start", headers=_bearer())
    assert response.status_code == 401
    assert redis.values == {}


@pytest.mark.parametrize("redirect_to", ["https://evil.test", "//evil.test"])
def test_bind_post_rejects_external_redirects(rig, redirect_to) -> None:
    client, redis, *_ = rig
    response = client.post(
        "/api/auth/oauth/github/bind/start", headers=_bearer(), params={"redirect_to": redirect_to},
    )
    assert response.status_code == 400
    assert redis.values == {}


# ---------------------------------------------------------------------------
# callback 分支
# ---------------------------------------------------------------------------


def _browser_cookies(client: TestClient, browser: str = "browser-token") -> None:
    client.cookies.set("aigc_oauth_browser", browser)


def test_callback_bind_binds_identity_and_redirects_to_action_callback(rig) -> None:
    client, redis, users, identities, adapter = rig
    state = _seed_state(redis, bind=True)
    _browser_cookies(client)

    response = client.get(
        f"/api/auth/oauth/github/callback?state={state}&code=code-1",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "https://example.test/oauth/action-callback"
    set_cookie = response.headers["set-cookie"]
    assert "aigc_oauth_bind_handoff=" in set_cookie
    assert "aigc_oauth_handoff=" not in set_cookie.replace("aigc_oauth_bind_handoff", "")
    assert identities.bind_calls == [
        {
            "user_id": 7,
            "provider": "github",
            "provider_subject": "gh-42",
            "display_email": "gh@example.test",
            "email_verified": True,
        }
    ]
    # 绑定分支绝不触碰登录解析
    assert identities.resolve_calls == []
    handoff_keys = [
        k for k in redis.values if k.startswith(OAUTH_BIND_HANDOFF_PREFIX)
    ]
    assert len(handoff_keys) == 1
    handoff = json.loads(redis.values[handoff_keys[0]])
    assert handoff["user_id"] == 7
    assert handoff["provider"] == "github"
    assert handoff["status"] == "bound"
    assert handoff["redirect_to"] == "/settings?tab=oauth"


def test_callback_login_branch_unaffected(rig) -> None:
    client, redis, users, identities, adapter = rig
    state = _seed_state(redis, bind=False)
    _browser_cookies(client)

    response = client.get(
        f"/api/auth/oauth/github/callback?state={state}&code=code-1",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "https://example.test/oauth/callback"
    assert "aigc_oauth_handoff=" in response.headers["set-cookie"]
    assert "aigc_oauth_bind_handoff=" not in response.headers["set-cookie"]
    assert len(identities.resolve_calls) == 1
    assert identities.bind_calls == []


def test_callback_bind_owned_by_other_is_conflict_without_handoff(rig) -> None:
    client, redis, users, identities, adapter = rig
    identities.bind_status = "owned_by_other"
    state = _seed_state(redis, bind=True)
    _browser_cookies(client)

    response = client.get(
        f"/api/auth/oauth/github/callback?state={state}&code=code-1",
        follow_redirects=False,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "oauth_identity_conflict"
    assert redis.values == {}


def test_callback_bind_missing_target_user_rejected(rig) -> None:
    client, redis, users, identities, adapter = rig
    users.user = None
    state = _seed_state(redis, bind=True)
    _browser_cookies(client)

    response = client.get(
        f"/api/auth/oauth/github/callback?state={state}&code=code-1",
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "oauth_account_invalid"
    assert identities.bind_calls == []


def test_callback_bind_disabled_target_user_rejected(rig) -> None:
    client, redis, users, identities, adapter = rig
    users.user = {**USER, "disabled": True}
    state = _seed_state(redis, bind=True)
    _browser_cookies(client)

    response = client.get(
        f"/api/auth/oauth/github/callback?state={state}&code=code-1",
        follow_redirects=False,
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "oauth_account_disabled"
    assert identities.bind_calls == []


def test_callback_rejects_bind_payload_in_login_namespace(rig) -> None:
    """命名空间与载荷判别不一致（bind 载荷出现在登录空间）一律按无效 state。"""
    client, redis, *_ = rig
    state = _seed_state(
        redis, bind=True, namespace_override="auth:oauth:state:"
    )
    _browser_cookies(client)

    response = client.get(
        f"/api/auth/oauth/github/callback?state={state}&code=code-1",
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "oauth_state_invalid"


def test_callback_rejects_login_payload_in_bind_namespace(rig) -> None:
    client, redis, *_ = rig
    state = _seed_state(redis, bind=False, namespace_override=OAUTH_BIND_STATE_PREFIX)
    _browser_cookies(client)

    response = client.get(
        f"/api/auth/oauth/github/callback?state={state}&code=code-1",
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "oauth_state_invalid"


def test_callback_state_is_one_time(rig) -> None:
    client, redis, *_ = rig
    state = _seed_state(redis, bind=True)
    _browser_cookies(client)

    first = client.get(
        f"/api/auth/oauth/github/callback?state={state}&code=code-1",
        follow_redirects=False,
    )
    second = client.get(
        f"/api/auth/oauth/github/callback?state={state}&code=code-1",
        follow_redirects=False,
    )

    assert first.status_code == 303
    assert second.status_code == 400
    assert second.json()["detail"] == "oauth_state_invalid"


def test_callback_rejects_browser_binding_mismatch(rig) -> None:
    client, redis, *_ = rig
    state = _seed_state(redis, bind=True, browser="expected-browser")
    _browser_cookies(client, browser="wrong-browser")

    response = client.get(
        f"/api/auth/oauth/github/callback?state={state}&code=code-1",
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "oauth_state_invalid"


def test_callback_rejects_provider_mismatch(rig, monkeypatch) -> None:
    client, redis, *_ = rig
    monkeypatch.setattr(
        routes_oauth, "configured_oauth_providers",
        lambda **kwargs: ["github", "google"],
    )
    monkeypatch.setattr(
        routes_oauth, "build_oauth_adapters",
        lambda config: {"github": FakeAdapter(), "google": FakeAdapter(subject="g-1")},
    )
    state = _seed_state(redis, bind=True, provider="github")
    _browser_cookies(client)

    response = client.get(
        f"/api/auth/oauth/google/callback?state={state}&code=code-1",
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "oauth_state_invalid"


# ---------------------------------------------------------------------------
# bind/consume
# ---------------------------------------------------------------------------


def test_bind_consume_requires_authentication(rig) -> None:
    client, redis, *_ = rig
    handoff = _seed_bind_handoff(redis)
    client.cookies.set("aigc_oauth_bind_handoff", handoff)

    response = client.post("/api/auth/oauth/bind/consume")

    assert response.status_code == 401


def test_bind_consume_success_reports_status_without_token(rig) -> None:
    client, redis, *_ = rig
    handoff = _seed_bind_handoff(redis)
    client.cookies.set("aigc_oauth_browser", "browser-token")
    client.cookies.set("aigc_oauth_bind_handoff", handoff)

    response = client.post("/api/auth/oauth/bind/consume", headers=_bearer())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.json() == {
        "provider": "github",
        "status": "bound",
        "redirect_to": "/settings?tab=oauth",
    }
    set_cookie = response.headers["set-cookie"]
    assert 'aigc_oauth_bind_handoff=""' in set_cookie
    assert 'aigc_oauth_browser=""' in set_cookie

    replay = client.post("/api/auth/oauth/bind/consume", headers=_bearer())
    assert replay.status_code == 400
    assert replay.json()["detail"] == "oauth_handoff_invalid"


def test_bind_consume_reports_already_bound_idempotent_status(rig) -> None:
    client, redis, *_ = rig
    handoff = _seed_bind_handoff(redis, status="already_bound")
    client.cookies.set("aigc_oauth_browser", "browser-token")
    client.cookies.set("aigc_oauth_bind_handoff", handoff)

    response = client.post("/api/auth/oauth/bind/consume", headers=_bearer())

    assert response.status_code == 200
    assert response.json()["status"] == "already_bound"


def test_bind_consume_rejects_handoff_owned_by_another_user(rig) -> None:
    client, redis, *_ = rig
    handoff = _seed_bind_handoff(redis, user_id=8)
    client.cookies.set("aigc_oauth_browser", "browser-token")
    client.cookies.set("aigc_oauth_bind_handoff", handoff)

    response = client.post("/api/auth/oauth/bind/consume", headers=_bearer(user_id=7))

    assert response.status_code == 400
    assert response.json()["detail"] == "oauth_handoff_invalid"
    assert redis.values == {}


def test_bind_consume_rejects_login_handoff_token(rig) -> None:
    """登录命名空间的 handoff 对绑定 consume 不可见（跨操作重放被拒）。"""
    client, redis, *_ = rig
    login_handoff = _seed_login_handoff(redis)
    client.cookies.set("aigc_oauth_browser", "browser-token")
    client.cookies.set("aigc_oauth_bind_handoff", login_handoff)

    response = client.post("/api/auth/oauth/bind/consume", headers=_bearer())

    assert response.status_code == 400
    assert response.json()["detail"] == "oauth_handoff_invalid"
    # 登录 handoff 未被绑定 consume 消耗
    assert len(redis.values) == 1


def test_login_consume_rejects_bind_handoff_token(rig) -> None:
    client, redis, *_ = rig
    bind_handoff = _seed_bind_handoff(redis)
    client.cookies.set("aigc_oauth_browser", "browser-token")
    client.cookies.set("aigc_oauth_handoff", bind_handoff)

    response = client.post("/api/auth/oauth/consume")

    assert response.status_code == 400
    assert response.json()["detail"] == "oauth_handoff_invalid"
    assert len(redis.values) == 1


def test_bind_consume_binding_mismatch_spends_handoff(rig) -> None:
    client, redis, *_ = rig
    handoff = _seed_bind_handoff(redis, browser="expected-browser")
    client.cookies.set("aigc_oauth_browser", "wrong-browser")
    client.cookies.set("aigc_oauth_bind_handoff", handoff)

    response = client.post("/api/auth/oauth/bind/consume", headers=_bearer())

    assert response.status_code == 400
    assert response.json()["detail"] == "oauth_handoff_invalid"
    assert redis.values == {}
