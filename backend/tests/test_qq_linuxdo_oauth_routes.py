from __future__ import annotations

from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_oauth
from backend.app.api.dependencies import get_oauth_identity_repository, get_user_account_repository
from backend.app.core.auth import create_access_token, get_user_identity_repository
from backend.app.services.auth.oauth.contracts import OAuthProviderConfig
from backend.tests.test_auth_oauth_binding import USER, FakeIdentities, FakeRedis, FakeUsers
from backend.tests.test_qq_linuxdo_oauth import PROVIDERS, responses
from backend.tests.test_routes_oauth import _config


@pytest.fixture(params=["qq", "linuxdo"])
def rig(request, monkeypatch):
    provider = request.param
    config = replace(
        _config(), enabled_providers=("qq", "linuxdo"),
        qq_client_id="app-id", qq_client_secret="app-secret",
        linuxdo_client_id="app-id", linuxdo_client_secret="app-secret",
    )
    requests = []
    payloads = responses(provider)

    def handler(upstream_request):
        requests.append(upstream_request)
        return httpx.Response(200, json=payloads[(len(requests) - 1) % len(payloads)])

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapters = {
        name: factory(OAuthProviderConfig(name, "app-id", "app-secret"), http_client=upstream)
        for name, factory in PROVIDERS.items()
    }
    app = FastAPI()
    app.state.redis = FakeRedis()
    app.include_router(routes_oauth.router, prefix="/api")
    users, identities = FakeUsers(dict(USER)), FakeIdentities()
    app.dependency_overrides[get_oauth_identity_repository] = lambda: identities
    app.dependency_overrides[get_user_account_repository] = lambda: users
    app.dependency_overrides[get_user_identity_repository] = lambda: users
    monkeypatch.setattr(routes_oauth, "_config", lambda request: config)
    monkeypatch.setattr(routes_oauth, "build_oauth_adapters", lambda config: adapters)
    with TestClient(app, base_url="https://example.test") as client:
        yield provider, client, identities, requests, config
    import asyncio
    asyncio.run(upstream.aclose())


def start(provider, client, *, bind=False, method="GET"):
    headers = {"Authorization": "Bearer " + create_access_token({"user_id": 7, "role": "user", "pwd_ver": 1})}
    path = "bind/start" if bind else "start"
    response = client.request(method, f"/api/auth/oauth/{provider}/{path}?redirect_to=/projects", headers=headers, follow_redirects=False)
    assert response.status_code == (200 if method == "POST" else 307)
    url = response.json()["authorization_url"] if method == "POST" else response.headers["location"]
    params = parse_qs(urlsplit(url).query)
    assert params["redirect_uri"] == [f"https://example.test/api/auth/oauth/{provider}/callback"]
    return params["state"][0]


def test_new_provider_login_and_single_use_handoff(rig):
    provider, client, identities, requests, _ = rig
    state = start(provider, client)
    path = f"/api/auth/oauth/{provider}/callback?state={state}&code=code"
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "https://example.test/oauth/callback"
    assert identities.resolve_calls[0]["provider"] == provider
    assert identities.resolve_calls[0]["display_email"] is None
    assert identities.resolve_calls[0]["email_verified"] is False
    assert not identities.bind_calls
    assert client.post("/api/auth/oauth/consume").json()["redirect_to"] == "/projects"
    assert client.post("/api/auth/oauth/consume").status_code == 400
    assert client.get(path).status_code == 400
    assert len(requests) == len(responses(provider))


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_new_provider_bind_does_not_create_login_session(rig, method):
    provider, client, identities, _, _ = rig
    state = start(provider, client, bind=True, method=method)
    response = client.get(f"/api/auth/oauth/{provider}/callback?state={state}&code=code", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].endswith("/oauth/action-callback")
    assert identities.bind_calls[0]["provider"] == provider
    assert identities.bind_calls[0]["user_id"] == 7
    assert not identities.resolve_calls
    assert not client.cookies.get("aigc_oauth_handoff")
    headers = {"Authorization": "Bearer " + create_access_token({"user_id": 7, "role": "user", "pwd_ver": 1})}
    consumed = client.post("/api/auth/oauth/bind/consume", headers=headers)
    assert consumed.json() == {"provider": provider, "status": "bound", "redirect_to": "/projects"}
    assert client.post("/api/auth/oauth/bind/consume", headers=headers).status_code == 400


@pytest.mark.parametrize("failure", ["wrong_provider", "wrong_browser", "cancelled"])
def test_invalid_new_provider_callbacks_never_contact_upstream(rig, failure):
    provider, client, identities, requests, _ = rig
    state = start(provider, client)
    if failure == "wrong_provider":
        provider = "linuxdo" if provider == "qq" else "qq"
    if failure == "wrong_browser":
        client.cookies.clear()
    query = f"state={state}&code=code"
    if failure == "cancelled":
        query = f"state={state}&error=access_denied"
    response = client.get(f"/api/auth/oauth/{provider}/callback?{query}")
    assert response.status_code == 400
    assert not requests and not identities.resolve_calls and not identities.bind_calls


def test_unconfigured_new_provider_fails_closed(rig, monkeypatch):
    provider, client, _, requests, config = rig
    monkeypatch.setattr(routes_oauth, "_config", lambda request: replace(config, **{f"{provider}_client_secret": ""}))
    assert client.get(f"/api/auth/oauth/{provider}/start").status_code == 503
    assert not requests


def test_existing_identity_cannot_be_bound_to_another_account(rig):
    provider, client, identities, _, _ = rig
    identities.bind_status = "owned_by_other"
    state = start(provider, client, bind=True)
    response = client.get(f"/api/auth/oauth/{provider}/callback?state={state}&code=code", follow_redirects=False)
    assert response.status_code == 409
    assert not identities.resolve_calls
    assert not client.cookies.get("aigc_oauth_bind_handoff")
