"""OAuth 按入口回调的契约测试：备用入口发起的登录/绑定全程留在该入口。

边缘 Caddy 回源时 Host 统一改写为 canonical，原始入口只经 X-Forwarded-Host 带到
后端；该头仅用于在白名单内选择入口，未命中（含伪造、多值、带端口）一律回落
canonical，且 authorize 与 exchange 的 redirect_uri 必须逐字节一致。
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_oauth
from backend.app.api.dependencies import (
    get_oauth_identity_repository,
    get_user_account_repository,
)
from backend.app.core.auth import create_access_token, get_user_identity_repository
from backend.app.core.config import Settings, settings
from backend.app.models.schema_oauth import OAuthStatePayload
from backend.app.repositories.oauth_identity_repository import OAuthBindResult
from backend.app.services.auth.oauth import redirect
from backend.app.services.auth.oauth.contracts import OAuthProfile, OAuthProviderConfig
from backend.app.services.auth.oauth.providers.wechat import WeChatIdentity, WeChatOAuthProvider
from backend.app.services.auth.oauth.runtime_config import EffectiveOAuthConfig
from backend.app.services.auth.oauth.state import (
    OAUTH_BIND_STATE_PREFIX,
    OAUTH_STATE_PREFIX,
    create_state_material,
    digest_secret,
    state_key,
)

CANONICAL = "https://example.test"
MIRROR = "https://aigcradar.online"


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value

    async def getdel(self, key: str):
        return self.values.pop(key, None)


class FakeUsers:
    def get_user_by_id(self, user_id: int):
        return {"id": user_id, "role": "user", "email": "u@example.test", "pwd_ver": 1}


class FakeIdentities:
    def resolve_first_login(self, **kwargs: Any):
        return type(
            "Resolution",
            (),
            {"status": "authenticated", "user": {"id": 7, "role": "user", "pwd_ver": 1}},
        )()

    def bind_identity(self, **kwargs: Any) -> OAuthBindResult:
        return OAuthBindResult(status="bound")


class FakeAdapter:
    use_pkce = True
    use_nonce = False

    def __init__(self) -> None:
        self.authorize_calls: list[str] = []
        self.exchange_calls: list[dict[str, Any]] = []

    def authorization_url(
        self,
        *,
        state: str,
        redirect_uri: str,
        code_challenge: str | None = None,
        nonce: str | None = None,
    ) -> str:
        self.authorize_calls.append(redirect_uri)
        return f"https://provider.test/authorize?state={state}"

    async def exchange_code(self, **kwargs: Any) -> OAuthProfile:
        self.exchange_calls.append(kwargs)
        return OAuthProfile(
            provider_subject="gh-42", email="gh@example.test",
            email_verified=True, username="ghuser",
        )


def _config() -> EffectiveOAuthConfig:
    return EffectiveOAuthConfig(
        enabled_providers=(),
        public_base_url=CANONICAL,
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


@pytest.fixture(autouse=True)
def mirror_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "oauth_alternate_base_urls", MIRROR)


@pytest.fixture()
def rig(monkeypatch: pytest.MonkeyPatch):
    adapter = FakeAdapter()
    app = FastAPI()
    redis = FakeRedis()
    app.state.redis = redis
    app.include_router(routes_oauth.router, prefix="/api")
    users = FakeUsers()
    app.dependency_overrides[get_user_account_repository] = lambda: users
    app.dependency_overrides[get_user_identity_repository] = lambda: users
    app.dependency_overrides[get_oauth_identity_repository] = FakeIdentities
    monkeypatch.setattr(routes_oauth, "_config", lambda request: _config())
    monkeypatch.setattr(routes_oauth, "configured_oauth_providers", lambda **kwargs: ["github"])
    monkeypatch.setattr(routes_oauth, "build_oauth_adapters", lambda config: {"github": adapter})
    return TestClient(app, base_url=CANONICAL), redis, adapter


def _bearer() -> dict[str, str]:
    token = create_access_token({"user_id": 7, "role": "user", "pwd_ver": 1})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def wechat_rig(rig, monkeypatch: pytest.MonkeyPatch):
    client, redis, _ = rig
    adapter = WeChatOAuthProvider(OAuthProviderConfig(
        name="wechat", client_id="wx-website", client_secret="private-app-secret",
    ))
    monkeypatch.setattr(adapter, "exchange_code", AsyncMock(return_value=WeChatIdentity(
        subject="wechat-user", name="WeChat user",
    )))
    monkeypatch.setattr(routes_oauth, "configured_oauth_providers", lambda **kwargs: ["wechat"])
    monkeypatch.setattr(routes_oauth, "build_oauth_adapters", lambda config: {"wechat": adapter})
    return client, redis, adapter


@pytest.mark.parametrize("entry", [CANONICAL, MIRROR])
def test_prepared_wechat_login_round_trip_is_browser_bound_and_one_time(wechat_rig, entry) -> None:
    client, redis, adapter = wechat_rig
    headers = {"X-Forwarded-Host": urlsplit(entry).netloc}
    start = client.post(
        "/api/auth/oauth/wechat/start", headers=headers,
        params={"redirect_to": "/membership?plan=yearly"},
    )
    assert start.status_code == 200
    assert start.headers["cache-control"] == "no-store"
    assert set(start.json()) == {"authorization_url", "expires_in"}
    assert start.json()["expires_in"] == 300
    assert "private-app-secret" not in start.text
    cookie = start.headers["set-cookie"].lower()
    assert all(flag in cookie for flag in ("httponly", "secure", "samesite=lax"))
    url = urlsplit(start.json()["authorization_url"])
    assert url.netloc == "open.weixin.qq.com"
    assert url.path == "/connect/qrconnect"
    assert parse_qs(url.query)["scope"] == ["snsapi_login"]
    assert parse_qs(url.query)["redirect_uri"] == [f"{entry}/api/auth/oauth/wechat/callback"]
    payload = _stored_payload(redis, OAUTH_STATE_PREFIX)
    assert payload["operation"] == "login"
    assert payload["target_user_id"] is None
    assert payload["browser_binding_hash"] == digest_secret(client.cookies["aigc_oauth_browser"])
    params = {"code": "wechat-code", "state": _state_from(start.json()["authorization_url"])}
    callback = client.get("/api/auth/oauth/wechat/callback", params=params, follow_redirects=False)
    assert callback.status_code == 303
    assert callback.headers["location"] == f"{entry}/oauth/callback"
    assert adapter.exchange_code.await_args.kwargs["redirect_uri"] == f"{entry}/api/auth/oauth/wechat/callback"
    consume = client.post("/api/auth/oauth/consume")
    assert consume.status_code == 200
    assert consume.json()["redirect_to"] == "/membership?plan=yearly"
    assert client.get("/api/auth/oauth/wechat/callback", params=params).status_code == 400
    assert client.post("/api/auth/oauth/consume").status_code == 400


def test_prepared_wechat_login_cannot_be_used_by_another_browser(wechat_rig) -> None:
    client, _, adapter = wechat_rig
    start = client.post("/api/auth/oauth/wechat/start")
    client.cookies.clear()
    callback = client.get("/api/auth/oauth/wechat/callback", params={
        "state": _state_from(start.json()["authorization_url"]), "code": "wechat-code",
    })
    assert callback.status_code == 400
    assert callback.json()["detail"] == "oauth_state_invalid"
    adapter.exchange_code.assert_not_awaited()


@pytest.mark.parametrize("target", ["//evil.test", "https://evil.test", "/%5cevil.test"])
def test_prepared_wechat_login_rejects_external_return_paths(wechat_rig, target) -> None:
    client, redis, adapter = wechat_rig
    start = client.post("/api/auth/oauth/wechat/start", params={"redirect_to": target})
    assert start.status_code == 400
    assert start.json()["detail"] == "oauth_redirect_invalid"
    assert not redis.values
    adapter.exchange_code.assert_not_awaited()


def _state_from(location: str) -> str:
    return parse_qs(urlsplit(location).query)["state"][0]


def _stored_payload(redis: FakeRedis, prefix: str) -> dict[str, Any]:
    keys = [key for key in redis.values if key.startswith(prefix)]
    assert len(keys) == 1
    return json.loads(redis.values[keys[0]])


# ---------------------------------------------------------------------------
# 白名单解析
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("header", ["aigcradar.online", "AIGCRADAR.ONLINE", " aigcradar.online "])
def test_forwarded_host_on_allowlist_selects_the_mirror(header: str) -> None:
    assert redirect.alternate_entry_for_forwarded_host(header, _config()) == MIRROR


@pytest.mark.parametrize(
    "header",
    [
        None, "", "example.test", "www.aigcnews.cn", "evil.test",
        "www.aigcradar.online", "aigcradar.online:443",
        "aigcradar.online, evil.test", "evil.test, aigcradar.online",
        "aigcradar.online.evil.test", "https://aigcradar.online",
    ],
)
def test_forwarded_host_off_allowlist_falls_back_to_canonical(header: str | None) -> None:
    assert redirect.alternate_entry_for_forwarded_host(header, _config()) is None


def test_empty_allowlist_disables_alternate_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "oauth_alternate_base_urls", "")

    assert redirect.alternate_entry_for_forwarded_host("aigcradar.online", _config()) is None


def test_allowlisted_canonical_host_is_not_an_alternate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "oauth_alternate_base_urls", f"{CANONICAL},{MIRROR}")

    assert redirect.alternate_entry_for_forwarded_host("example.test", _config()) is None


def test_entry_base_url_restores_canonical_or_allowlisted_entry_only() -> None:
    assert redirect.entry_base_url(None, _config()) == CANONICAL
    assert redirect.entry_base_url(MIRROR, _config()) == MIRROR
    with pytest.raises(redirect.OAuthRedirectError):
        redirect.entry_base_url("https://evil.test", _config())


def test_settings_normalize_alternate_origins() -> None:
    parsed = Settings(
        _env_file=None,
        oauth_alternate_base_urls=" HTTPS://AigcRadar.online/ ,https://aigcradar.online,, ",
    )

    assert parsed.oauth_alternate_base_urls == MIRROR
    assert Settings(_env_file=None, oauth_alternate_base_urls="").oauth_alternate_base_urls == ""


@pytest.mark.parametrize(
    "value",
    [
        "http://aigcradar.online",
        "https://aigcradar.online/app",
        "https://aigcradar.online?x=1",
        "https://aigcradar.online#frag",
        "https://user:pass@aigcradar.online",
        "aigcradar.online",
        "https://",
    ],
)
def test_settings_reject_non_origin_alternates(value: str) -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, oauth_alternate_base_urls=value)


def test_legacy_state_without_entry_field_parses_as_canonical() -> None:
    legacy = {
        "provider": "github", "redirect_to": "/", "pkce_verifier": "v" * 43,
        "nonce": None, "browser_binding_hash": "a" * 64, "operation": "login",
        "target_user_id": None,
    }

    assert OAuthStatePayload.model_validate_json(json.dumps(legacy)).entry_base_url is None


# ---------------------------------------------------------------------------
# 登录：start → callback 全程同入口
# ---------------------------------------------------------------------------


def test_start_without_forwarded_host_keeps_canonical_callback(rig) -> None:
    client, redis, adapter = rig

    response = client.get("/api/auth/oauth/github/start", follow_redirects=False)

    assert response.status_code == 307
    assert adapter.authorize_calls == [f"{CANONICAL}/api/auth/oauth/github/callback"]
    assert _stored_payload(redis, OAUTH_STATE_PREFIX)["entry_base_url"] is None


def test_start_with_spoofed_forwarded_host_keeps_canonical_callback(rig) -> None:
    client, redis, adapter = rig

    response = client.get(
        "/api/auth/oauth/github/start",
        headers={"X-Forwarded-Host": "evil.test"},
        follow_redirects=False,
    )

    assert response.status_code == 307
    assert adapter.authorize_calls == [f"{CANONICAL}/api/auth/oauth/github/callback"]
    assert _stored_payload(redis, OAUTH_STATE_PREFIX)["entry_base_url"] is None


def test_mirror_login_round_trip_stays_on_the_mirror(rig) -> None:
    client, redis, adapter = rig
    mirror = {"X-Forwarded-Host": "aigcradar.online"}

    start = client.get("/api/auth/oauth/github/start", headers=mirror, follow_redirects=False)

    mirror_callback = f"{MIRROR}/api/auth/oauth/github/callback"
    assert start.status_code == 307
    assert adapter.authorize_calls == [mirror_callback]
    assert _stored_payload(redis, OAUTH_STATE_PREFIX)["entry_base_url"] == MIRROR

    callback = client.get(
        "/api/auth/oauth/github/callback",
        params={"code": "provider-code", "state": _state_from(start.headers["location"])},
        headers=mirror,
        follow_redirects=False,
    )

    assert callback.status_code == 303
    # exchange 与 authorize 的 redirect_uri 逐字节一致，回跳留在镜像入口
    assert [call["redirect_uri"] for call in adapter.exchange_calls] == [mirror_callback]
    assert callback.headers["location"] == f"{MIRROR}/oauth/callback"
    assert "aigc_oauth_handoff=" in callback.headers["set-cookie"]


def test_canonical_login_callback_is_unchanged(rig) -> None:
    client, _, adapter = rig

    start = client.get("/api/auth/oauth/github/start", follow_redirects=False)
    callback = client.get(
        "/api/auth/oauth/github/callback",
        params={"code": "provider-code", "state": _state_from(start.headers["location"])},
        follow_redirects=False,
    )

    assert callback.status_code == 303
    assert adapter.exchange_calls[0]["redirect_uri"] == f"{CANONICAL}/api/auth/oauth/github/callback"
    assert callback.headers["location"] == f"{CANONICAL}/oauth/callback"


def test_legacy_state_in_redis_completes_on_canonical(rig) -> None:
    """升级前写入 Redis、不含 entry_base_url 的 state 仍按 canonical 走完。"""
    client, redis, adapter = rig
    browser = "legacy-browser"
    material = create_state_material(use_pkce=True, use_nonce=False)
    redis.values[state_key(material.state)] = json.dumps({
        "provider": "github", "redirect_to": "/", "pkce_verifier": material.code_verifier,
        "nonce": None, "browser_binding_hash": digest_secret(browser),
    })
    client.cookies.set("aigc_oauth_browser", browser)

    callback = client.get(
        "/api/auth/oauth/github/callback",
        params={"code": "provider-code", "state": material.state},
        follow_redirects=False,
    )

    assert callback.status_code == 303
    assert adapter.exchange_calls[0]["redirect_uri"] == f"{CANONICAL}/api/auth/oauth/github/callback"
    assert callback.headers["location"] == f"{CANONICAL}/oauth/callback"


def test_state_entry_removed_from_allowlist_fails_closed(
    rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, adapter = rig
    start = client.get(
        "/api/auth/oauth/github/start",
        headers={"X-Forwarded-Host": "aigcradar.online"},
        follow_redirects=False,
    )
    monkeypatch.setattr(settings, "oauth_alternate_base_urls", "")

    callback = client.get(
        "/api/auth/oauth/github/callback",
        params={"code": "provider-code", "state": _state_from(start.headers["location"])},
        follow_redirects=False,
    )

    assert callback.status_code == 503
    assert callback.json()["detail"] == "oauth_unavailable"
    assert adapter.exchange_calls == []


# ---------------------------------------------------------------------------
# 绑定：同样按入口回调，回跳绑定专用前端路径
# ---------------------------------------------------------------------------


def test_mirror_bind_round_trip_stays_on_the_mirror(rig) -> None:
    client, redis, adapter = rig
    mirror = {"X-Forwarded-Host": "aigcradar.online"}

    start = client.get(
        "/api/auth/oauth/github/bind/start",
        headers={**_bearer(), **mirror},
        follow_redirects=False,
    )

    mirror_callback = f"{MIRROR}/api/auth/oauth/github/callback"
    assert start.status_code == 307
    assert adapter.authorize_calls == [mirror_callback]
    payload = _stored_payload(redis, OAUTH_BIND_STATE_PREFIX)
    assert payload["operation"] == "bind"
    assert payload["entry_base_url"] == MIRROR

    callback = client.get(
        "/api/auth/oauth/github/callback",
        params={"code": "provider-code", "state": _state_from(start.headers["location"])},
        headers=mirror,
        follow_redirects=False,
    )

    assert callback.status_code == 303
    assert [call["redirect_uri"] for call in adapter.exchange_calls] == [mirror_callback]
    assert callback.headers["location"] == f"{MIRROR}/oauth/action-callback"
    assert "aigc_oauth_bind_handoff=" in callback.headers["set-cookie"]


def test_payload_rejects_non_url_entry_lengths() -> None:
    base = {
        "provider": "github", "redirect_to": "/", "browser_binding_hash": "a" * 64,
    }
    with pytest.raises(ValueError):
        OAuthStatePayload(**base, entry_base_url="")
    with pytest.raises(ValueError):
        OAuthStatePayload(**base, entry_base_url="https://" + "a" * 1100)
