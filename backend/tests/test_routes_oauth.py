from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_oauth
from backend.app.api.dependencies import (
    get_user_account_repository,
)
from backend.app.models.schema_oauth import OAuthHandoffPayload
from backend.app.services.auth.oauth.handoff import OAuthHandoffStore
from backend.app.services.auth.oauth.runtime_config import EffectiveOAuthConfig
from backend.app.services.auth.oauth.state import digest_secret


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value

    async def getdel(self, key: str):
        return self.values.pop(key, None)


class FakeUsers:
    def __init__(self, user: dict[str, object] | None) -> None:
        self.user = user

    def get_user_by_id(self, user_id: int):
        return self.user


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


def _client(user: dict[str, object] | None = None) -> tuple[TestClient, FakeRedis]:
    app = FastAPI()
    redis = FakeRedis()
    app.state.redis = redis
    app.include_router(routes_oauth.router, prefix="/api")
    app.dependency_overrides[get_user_account_repository] = lambda: FakeUsers(user)
    return TestClient(app, base_url="https://example.test"), redis


def _issue_handoff(redis: FakeRedis, *, browser: str = "browser-token", user_id: int = 7) -> str:
    store = OAuthHandoffStore(redis, ttl_seconds=120)
    import asyncio

    return asyncio.run(
        store.put(
            OAuthHandoffPayload(
                user_id=user_id,
                redirect_to="/settings?tab=oauth",
                browser_binding_hash=digest_secret(browser),
            )
        )
    )


def test_consume_requires_cookie_and_ignores_json_handoff(monkeypatch) -> None:
    client, _ = _client({"id": 7, "role": "user", "email": "u@example.test", "pwd_ver": 1})
    monkeypatch.setattr(routes_oauth, "_config", lambda request: _config())

    response = client.post(
        "/api/auth/oauth/consume",
        json={"handoff": "a" * 32},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "oauth_handoff_invalid"


def test_preparing_unconfigured_wechat_login_fails_without_creating_state(monkeypatch) -> None:
    client, redis = _client()
    monkeypatch.setattr(routes_oauth, "_config", lambda request: _config())
    response = client.post("/api/auth/oauth/wechat/start")
    assert response.status_code == 503
    assert response.json()["detail"] == "oauth_provider_unavailable"
    assert not redis.values
    assert "set-cookie" not in response.headers


def test_consume_success_is_cookie_only_and_clears_one_time_cookies(monkeypatch) -> None:
    client, redis = _client({"id": 7, "role": "user", "email": "u@example.test", "pwd_ver": 3})
    monkeypatch.setattr(routes_oauth, "_config", lambda request: _config())
    browser = "browser-token"
    handoff = _issue_handoff(redis, browser=browser)
    client.cookies.set("aigc_oauth_browser", browser)
    client.cookies.set("aigc_oauth_handoff", handoff)

    response = client.post("/api/auth/oauth/consume")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["role"] == "user"
    assert response.json()["redirect_to"] == "/settings?tab=oauth"
    assert 'aigc_oauth_handoff=""' in response.headers["set-cookie"]
    assert 'aigc_oauth_browser=""' in response.headers["set-cookie"]
    assert handoff.encode() not in response.url.query

    replay = client.post("/api/auth/oauth/consume")
    assert replay.status_code == 400
    assert replay.json()["detail"] == "oauth_handoff_invalid"


def test_consume_binding_mismatch_is_invalid_and_handoff_is_already_spent(monkeypatch) -> None:
    client, redis = _client({"id": 7, "role": "user", "email": "u@example.test", "pwd_ver": 1})
    monkeypatch.setattr(routes_oauth, "_config", lambda request: _config())
    handoff = _issue_handoff(redis, browser="expected-browser")
    client.cookies.set("aigc_oauth_browser", "wrong-browser")
    client.cookies.set("aigc_oauth_handoff", handoff)

    response = client.post("/api/auth/oauth/consume")

    assert response.status_code == 400
    assert response.json()["detail"] == "oauth_handoff_invalid"
    assert not redis.values


def test_consume_disabled_user_has_distinct_error(monkeypatch) -> None:
    client, redis = _client({"id": 7, "role": "user", "email": "u@example.test", "disabled": True})
    monkeypatch.setattr(routes_oauth, "_config", lambda request: _config())
    browser = "browser-token"
    handoff = _issue_handoff(redis, browser=browser)
    client.cookies.set("aigc_oauth_browser", browser)
    client.cookies.set("aigc_oauth_handoff", handoff)

    response = client.post("/api/auth/oauth/consume")

    assert response.status_code == 401
    assert response.json()["detail"] == "oauth_account_disabled"
