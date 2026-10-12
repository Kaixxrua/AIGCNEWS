"""MCP OAuth 端点契约：动态注册、同意页两步、令牌端点，以及完整授权流程。"""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, quote, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_mcp_oauth
from backend.app.api.dependencies import get_mcp_access_token_repository
from backend.app.api.routes_auth import MCP_CLIENT_TYPES
from backend.app.services.auth.mcp_oauth import (
    MCP_OAUTH_RESOURCE,
    PREREGISTERED_CLIENTS,
    infer_client_type,
    pkce_s256_challenge,
    preregistered_client,
    validate_redirect_uri,
)

REDIRECT = "http://localhost:43123/callback"
BOTH_SCOPES = ["projects:favorites:read", "tracking:read"]
SMITHERY_CLIENT_ID = "https://connect.smithery.ai/.well-known/oauth-client"
SMITHERY_REDIRECT = "https://connect.smithery.ai/oauth/callback"


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.counters: dict[str, int] = {}

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value

    async def getdel(self, key: str):
        return self.values.pop(key, None)

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def ttl(self, key: str) -> int:
        return 600

    async def expire(self, key: str, seconds: int) -> bool:
        return True


class FakeRepository:
    def __init__(self) -> None:
        self.clients: dict[str, dict[str, object]] = {}
        self.created: list[dict[str, object]] = []

    def register_mcp_oauth_client(self, **kwargs):
        client = {
            "client_id": kwargs["client_id"],
            "client_name": kwargs["client_name"],
            "redirect_uris": list(kwargs["redirect_uris"]),
            "token_endpoint_auth_method": kwargs["token_endpoint_auth_method"],
            "client_secret_hash": kwargs["client_secret_hash"],
            "created_at": "2026-10-06T00:00:00Z",
            "last_authorized_at": None,
        }
        self.clients[client["client_id"]] = client
        return dict(client)

    def get_mcp_oauth_client(self, client_id: str):
        client = self.clients.get(client_id)
        return dict(client) if client else None

    def create_user_mcp_token(self, **kwargs):
        self.created.append(kwargs)
        return {"token_metadata": {"id": len(self.created)}, "replaced_count": 0}


def _app(*, redis: FakeRedis | None = None, authenticated: bool = True, user_id: int = 7):
    app = FastAPI()
    app.state.redis = redis if redis is not None else FakeRedis()
    app.include_router(routes_mcp_oauth.router, prefix="/api")
    repository = FakeRepository()
    app.dependency_overrides[get_mcp_access_token_repository] = lambda: repository
    if authenticated:

        async def user():
            return {"user_id": user_id, "role": "user"}

        app.dependency_overrides[routes_mcp_oauth.RequireUser] = user
    return TestClient(app, base_url="https://aigcnews.cn"), repository, app


def _register(client: TestClient, **overrides):
    body = {
        "client_name": "Claude Code (aigc-news)",
        "redirect_uris": [REDIRECT],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    }
    body.update(overrides)
    return client.post("/api/oauth/register", json=body)


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    return verifier, pkce_s256_challenge(verifier)


def _authorization(client_id: str, challenge: str, /, **overrides):
    body = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT,
        "state": "st-1",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": "projects:favorites:read tracking:read",
        "resource": MCP_OAUTH_RESOURCE,
    }
    body.update(overrides)
    return {key: value for key, value in body.items() if value is not None}


def _approve(client: TestClient, client_id: str, challenge: str, **overrides) -> str:
    response = client.post(
        "/api/oauth/authorize",
        json={**_authorization(client_id, challenge, **overrides), "decision": "approve"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
    return response.json()["redirect_to"]


def _query(url: str) -> dict[str, list[str]]:
    return parse_qs(urlsplit(url).query)


def _exchange(client: TestClient, form: dict[str, str], **kwargs):
    return client.post("/api/oauth/token", data=form, **kwargs)


def _code_form(client_id: str, redirect_to: str, verifier: str, **overrides) -> dict[str, str]:
    form = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": _query(redirect_to)["code"][0],
        "redirect_uri": REDIRECT,
        "code_verifier": verifier,
        "resource": MCP_OAUTH_RESOURCE,
    }
    form.update(overrides)
    return {key: value for key, value in form.items() if value is not None}


def test_full_flow_issues_regular_mcp_token_bound_to_client() -> None:
    client, repository, _ = _app()

    registered = _register(client)
    assert registered.status_code == 201
    assert registered.headers["cache-control"] == "no-store"
    info = registered.json()
    client_id = info["client_id"]
    assert client_id.startswith("aigc_oc_")
    assert info["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in info
    assert info["redirect_uris"] == [REDIRECT]
    # 只回本站实际支持的取值；客户端声明的 refresh_token 被替换掉（RFC 7591 §3.2.1）
    assert info["grant_types"] == ["authorization_code"]
    assert info["response_types"] == ["code"]
    assert info["client_name"] == "Claude Code (aigc-news)"
    assert isinstance(info["client_id_issued_at"], int)

    verifier, challenge = _pkce()
    preview = client.post("/api/oauth/authorize/preview", json=_authorization(client_id, challenge))
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "no-store"
    assert preview.json() == {
        "status": "ready",
        "client": {
            "client_id": client_id,
            "client_name": "Claude Code (aigc-news)",
            "registered_at": "2026-10-06T00:00:00Z",
        },
        "redirect_uri": REDIRECT,
        "redirect": {"kind": "loopback", "host": "localhost"},
        "scopes": BOTH_SCOPES,
        "resource": MCP_OAUTH_RESOURCE,
    }

    redirect_to = _approve(client, client_id, challenge)
    assert redirect_to.startswith(REDIRECT + "?code=")
    query = _query(redirect_to)
    assert query["state"] == ["st-1"]
    assert query["iss"] == ["https://aigcnews.cn"]

    token = _exchange(client, _code_form(client_id, redirect_to, verifier))
    assert token.status_code == 200, token.text
    assert token.headers["cache-control"] == "no-store"
    assert token.headers["pragma"] == "no-cache"
    payload = token.json()
    assert set(payload) == {"access_token", "token_type", "scope"}
    assert payload["access_token"].startswith("aigc_mcp_")
    assert payload["token_type"] == "Bearer"
    assert payload["scope"] == "projects:favorites:read tracking:read"

    (created,) = repository.created
    assert created == {
        "user_id": 7,
        "token_hash": hashlib.sha256(payload["access_token"].encode()).hexdigest(),
        "token_hint": f"{payload['access_token'][:12]}...{payload['access_token'][-4:]}",
        "scopes": BOTH_SCOPES,
        "client_type": "claude",
        "client_label": "Claude Code (aigc-news)",
        "expires_at": None,
        "oauth_client_id": client_id,
    }

    replay = _exchange(client, _code_form(client_id, redirect_to, verifier))
    assert replay.status_code == 400
    assert replay.json()["error"] == "invalid_grant"
    assert len(repository.created) == 1


def test_registration_defaults_to_confidential_client_per_rfc7591() -> None:
    client, repository, _ = _app()
    response = client.post(
        "/api/oauth/register",
        json={"client_name": "Some Web App", "redirect_uris": ["https://app.example/cb"]},
    )
    assert response.status_code == 201
    info = response.json()
    assert info["token_endpoint_auth_method"] == "client_secret_basic"
    assert info["client_secret"].startswith("aigc_ocs_")
    assert info["client_secret_expires_at"] == 0
    stored = repository.clients[info["client_id"]]
    assert stored["client_secret_hash"] == hashlib.sha256(info["client_secret"].encode()).hexdigest()

    explicit_null = _register(client, token_endpoint_auth_method=None, grant_types=None, response_types=None)
    assert explicit_null.status_code == 201
    assert explicit_null.json()["token_endpoint_auth_method"] == "client_secret_basic"


def test_registration_sanitizes_name_and_deduplicates_redirects() -> None:
    client, repository, _ = _app()
    response = _register(client, client_name=" Evil‮  Name\n", redirect_uris=[REDIRECT, REDIRECT])
    assert response.status_code == 201
    assert response.json()["client_name"] == "Evil Name"
    assert response.json()["redirect_uris"] == [REDIRECT]
    nameless = _register(client, client_name=None)
    assert "client_name" not in nameless.json()
    assert repository.clients[nameless.json()["client_id"]]["client_name"] == ""


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"redirect_uris": None}, "invalid_redirect_uri"),
        ({"redirect_uris": []}, "invalid_redirect_uri"),
        ({"redirect_uris": "http://localhost:1/cb"}, "invalid_redirect_uri"),
        ({"redirect_uris": [f"http://localhost:{port}/cb" for port in range(1000, 1011)]}, "invalid_redirect_uri"),
        ({"redirect_uris": ["http://evil.example/cb"]}, "invalid_redirect_uri"),
        ({"redirect_uris": ["javascript:alert(1)"]}, "invalid_redirect_uri"),
        ({"redirect_uris": [REDIRECT, "https://app.example/cb#x"]}, "invalid_redirect_uri"),
        ({"token_endpoint_auth_method": "private_key_jwt"}, "invalid_client_metadata"),
        ({"grant_types": ["client_credentials"]}, "invalid_client_metadata"),
        ({"grant_types": "authorization_code"}, "invalid_client_metadata"),
        ({"response_types": ["token"]}, "invalid_client_metadata"),
        ({"client_name": ["Claude"]}, "invalid_client_metadata"),
    ],
)
def test_registration_rejects_invalid_metadata(overrides: dict[str, object], error: str) -> None:
    client, repository, _ = _app()
    body = {"client_name": "x", "redirect_uris": [REDIRECT], "token_endpoint_auth_method": "none"}
    body.update(overrides)
    body = {key: value for key, value in body.items() if value is not None}
    response = client.post("/api/oauth/register", json=body)
    assert response.status_code == 400
    assert response.json()["error"] == error
    assert response.headers["cache-control"] == "no-store"
    assert repository.clients == {}


@pytest.mark.parametrize("content", [b"not json", b"[]", b"x" * (16 * 1024 + 1)])
def test_registration_requires_a_small_json_object(content: bytes) -> None:
    client, repository, _ = _app()
    response = client.post(
        "/api/oauth/register", content=content, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"
    assert repository.clients == {}


def test_registration_is_rate_limited_per_ip_and_fails_closed_without_redis() -> None:
    client, repository, _ = _app()
    for _ in range(20):
        assert _register(client).status_code == 201
    limited = _register(client)
    assert limited.status_code == 429
    assert limited.json()["error"] == "temporarily_unavailable"
    assert len(repository.clients) == 20

    client, repository, app = _app()
    app.state.redis = None
    unavailable = _register(client)
    assert unavailable.status_code == 503
    assert unavailable.json()["error"] == "temporarily_unavailable"
    assert repository.clients == {}


@pytest.mark.parametrize("path", ["/api/oauth/authorize/preview", "/api/oauth/authorize"])
def test_unknown_client_or_redirect_never_redirects(path: str) -> None:
    client, _, _ = _app()
    client_id = _register(client).json()["client_id"]
    _, challenge = _pkce()
    cases = [
        (_authorization("aigc_oc_unknown", challenge), "invalid_client"),
        (_authorization("x" * 65, challenge), "invalid_client"),
        (_authorization(client_id, challenge, client_id=None), "invalid_request"),
        (_authorization(client_id, challenge, redirect_uri=None), "invalid_redirect_uri"),
        (_authorization(client_id, challenge, redirect_uri="https://evil.example/cb"), "invalid_redirect_uri"),
        (_authorization(client_id, challenge, redirect_uri="javascript:alert(1)"), "invalid_redirect_uri"),
        (_authorization(client_id, challenge, redirect_uri="http://127.0.0.1:43123/callback"), "invalid_redirect_uri"),
    ]
    for body, error in cases:
        response = client.post(path, json={**body, "decision": "approve"})
        assert response.status_code == 400, body
        assert response.json()["error"] == error
        assert "redirect_to" not in response.json()


@pytest.mark.parametrize("path", ["/api/oauth/authorize/preview", "/api/oauth/authorize"])
def test_later_authorization_errors_go_back_to_the_client(path: str) -> None:
    client, _, app = _app()
    client_id = _register(client).json()["client_id"]
    _, challenge = _pkce()
    cases = [
        ({"response_type": "token"}, "unsupported_response_type", "st-1"),
        ({"response_type": None}, "unsupported_response_type", "st-1"),
        ({"code_challenge_method": "plain"}, "invalid_request", "st-1"),
        ({"code_challenge_method": None}, "invalid_request", "st-1"),
        ({"code_challenge": None}, "invalid_request", "st-1"),
        ({"code_challenge": "too-short"}, "invalid_request", "st-1"),
        ({"resource": "https://aigcnews.cn/api/mcp"}, "invalid_target", "st-1"),
        ({"state": "s" * 2049}, "invalid_request", None),
    ]
    for overrides, error, state in cases:
        response = client.post(
            path, json={**_authorization(client_id, challenge, **overrides), "decision": "approve"}
        )
        assert response.status_code == 200, overrides
        body = response.json()
        assert body["status"] == "error"
        assert body["error"] == error
        assert body["redirect"] == {"kind": "loopback", "host": "localhost"}
        query = _query(body["redirect_to"])
        assert body["redirect_to"].startswith(REDIRECT + "?error=")
        assert query["error"] == [error]
        assert query["iss"] == ["https://aigcnews.cn"]
        assert query.get("state") == ([state] if state else None)
    assert [key for key in app.state.redis.values if key.startswith("auth:mcp-oauth:code:")] == []


def test_deny_returns_access_denied_without_issuing_a_code() -> None:
    client, repository, app = _app()
    client_id = _register(client).json()["client_id"]
    _, challenge = _pkce()
    response = client.post(
        "/api/oauth/authorize", json={**_authorization(client_id, challenge), "decision": "deny"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "denied"
    query = _query(response.json()["redirect_to"])
    assert query["error"] == ["access_denied"]
    assert query["state"] == ["st-1"]
    assert query["iss"] == ["https://aigcnews.cn"]
    assert app.state.redis.values == {}
    assert repository.created == []


def test_unknown_scopes_fall_back_to_defaults_and_subsets_are_honoured() -> None:
    client, _, _ = _app()
    client_id = _register(client).json()["client_id"]
    _, challenge = _pkce()
    for scope, granted in [
        ("openid offline_access", BOTH_SCOPES),
        (None, BOTH_SCOPES),
        ("tracking:read", ["tracking:read"]),
        ("projects:favorites:read openid", ["projects:favorites:read"]),
    ]:
        preview = client.post(
            "/api/oauth/authorize/preview", json=_authorization(client_id, challenge, scope=scope)
        )
        assert preview.json()["scopes"] == granted, scope


def test_loopback_port_may_change_but_token_redirect_must_match_authorization() -> None:
    client, _, _ = _app()
    client_id = _register(client, redirect_uris=["http://localhost:1111/callback"]).json()["client_id"]
    verifier, challenge = _pkce()
    redirect_to = _approve(client, client_id, challenge, redirect_uri="http://localhost:2222/callback")
    assert redirect_to.startswith("http://localhost:2222/callback?code=")

    mismatch = _exchange(
        client, _code_form(client_id, redirect_to, verifier, redirect_uri="http://localhost:1111/callback")
    )
    assert mismatch.json()["error"] == "invalid_grant"

    redirect_to = _approve(client, client_id, challenge, redirect_uri="http://localhost:2222/callback")
    ok = _exchange(
        client, _code_form(client_id, redirect_to, verifier, redirect_uri="http://localhost:2222/callback")
    )
    assert ok.status_code == 200, ok.text


def test_token_mismatches_burn_the_code() -> None:
    client, repository, _ = _app()
    client_id = _register(client).json()["client_id"]
    other_id = _register(client, client_name="Other").json()["client_id"]
    verifier, challenge = _pkce()

    redirect_to = _approve(client, client_id, challenge)
    wrong = _exchange(client, _code_form(client_id, redirect_to, "w" * 43))
    assert wrong.status_code == 400 and wrong.json()["error"] == "invalid_grant"
    burned = _exchange(client, _code_form(client_id, redirect_to, verifier))
    assert burned.status_code == 400 and burned.json()["error"] == "invalid_grant"

    redirect_to = _approve(client, client_id, challenge)
    stolen = _exchange(client, _code_form(other_id, redirect_to, verifier))
    assert stolen.json()["error"] == "invalid_grant"
    assert _exchange(client, _code_form(client_id, redirect_to, verifier)).json()["error"] == "invalid_grant"

    redirect_to = _approve(client, client_id, challenge)
    target = _exchange(client, _code_form(client_id, redirect_to, verifier, resource="https://evil.example/mcp"))
    assert target.status_code == 400 and target.json()["error"] == "invalid_target"

    redirect_to = _approve(client, client_id, challenge)
    no_resource = _exchange(client, _code_form(client_id, redirect_to, verifier, resource=None))
    assert no_resource.status_code == 200
    assert len(repository.created) == 1


def test_token_request_validation() -> None:
    client, repository, _ = _app()
    client_id = _register(client).json()["client_id"]
    verifier, challenge = _pkce()
    redirect_to = _approve(client, client_id, challenge)
    form = _code_form(client_id, redirect_to, verifier)

    cases = [
        ({**form, "grant_type": None}, 400, "invalid_request"),
        ({**form, "grant_type": "refresh_token"}, 400, "unsupported_grant_type"),
        ({**form, "grant_type": "client_credentials"}, 400, "unsupported_grant_type"),
        ({**form, "client_id": None}, 401, "invalid_client"),
        ({**form, "client_id": "aigc_oc_unknown"}, 401, "invalid_client"),
        ({**form, "code": None}, 400, "invalid_request"),
        ({**form, "redirect_uri": None}, 400, "invalid_request"),
        ({**form, "code_verifier": None}, 400, "invalid_request"),
    ]
    for data, status_code, error in cases:
        response = _exchange(client, {key: value for key, value in data.items() if value is not None})
        assert response.status_code == status_code, data
        assert response.json()["error"] == error
        assert response.headers["cache-control"] == "no-store"

    duplicated = "&".join(
        f"{key}={quote(value, safe='')}" for key, value in form.items()
    ) + "&code=second"
    response = client.post(
        "/api/oauth/token",
        content=duplicated,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"

    # 上面的请求都在核对授权码之前被拒，授权码仍然可用
    assert _exchange(client, form).status_code == 200
    assert len(repository.created) == 1


def _basic(client_id: str, secret: str) -> dict[str, str]:
    raw = f"{quote(client_id, safe='')}:{quote(secret, safe='')}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def test_confidential_clients_must_authenticate() -> None:
    client, repository, _ = _app()
    info = _register(client, token_endpoint_auth_method="client_secret_post").json()
    client_id, secret = info["client_id"], info["client_secret"]
    verifier, challenge = _pkce()
    redirect_to = _approve(client, client_id, challenge)
    form = _code_form(client_id, redirect_to, verifier)

    missing = _exchange(client, form)
    assert missing.status_code == 401 and missing.json()["error"] == "invalid_client"
    assert "www-authenticate" not in missing.headers
    wrong = _exchange(client, {**form, "client_secret": secret + "x"})
    assert wrong.status_code == 401
    wrong_basic = _exchange(client, {k: v for k, v in form.items() if k != "client_id"}, headers=_basic(client_id, "nope"))
    assert wrong_basic.status_code == 401
    assert wrong_basic.headers["www-authenticate"] == "Basic"
    both = _exchange(client, {**form, "client_secret": secret}, headers=_basic(client_id, secret))
    assert both.status_code == 400 and both.json()["error"] == "invalid_request"
    mismatch = _exchange(client, {**form, "client_id": "aigc_oc_other"}, headers=_basic(client_id, secret))
    assert mismatch.status_code == 400 and mismatch.json()["error"] == "invalid_request"
    garbage = _exchange(client, form, headers={"Authorization": "Basic !!!"})
    assert garbage.status_code == 401 and garbage.headers["www-authenticate"] == "Basic"
    assert repository.created == []

    # 认证都在核对授权码之前：上面的失败不消耗授权码
    ok = _exchange(client, {**form, "client_secret": secret})
    assert ok.status_code == 200, ok.text

    redirect_to = _approve(client, client_id, challenge)
    form = _code_form(client_id, redirect_to, verifier)
    basic = _exchange(client, {k: v for k, v in form.items() if k != "client_id"}, headers=_basic(client_id, secret))
    assert basic.status_code == 200, basic.text
    assert len(repository.created) == 2


def test_public_clients_ignore_presented_secrets() -> None:
    client, _, _ = _app()
    client_id = _register(client).json()["client_id"]
    verifier, challenge = _pkce()
    redirect_to = _approve(client, client_id, challenge)
    response = _exchange(client, {**_code_form(client_id, redirect_to, verifier), "client_secret": "anything"})
    assert response.status_code == 200


def test_preregistered_metadata_document_client_completes_the_flow_without_registering() -> None:
    client, repository, _ = _app()
    verifier, challenge = _pkce()

    preview = client.post(
        "/api/oauth/authorize/preview",
        json=_authorization(SMITHERY_CLIENT_ID, challenge, redirect_uri=SMITHERY_REDIRECT),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["client"] == {
        "client_id": SMITHERY_CLIENT_ID,
        "client_name": "Smithery Connect",
        "registered_at": None,
    }
    # 同意页显示的回调去向，就是对方文档里登记的域名
    assert preview.json()["redirect"] == {"kind": "web", "host": "connect.smithery.ai"}

    redirect_to = _approve(client, SMITHERY_CLIENT_ID, challenge, redirect_uri=SMITHERY_REDIRECT)
    assert redirect_to.startswith(SMITHERY_REDIRECT + "?code=")
    token = _exchange(
        client, _code_form(SMITHERY_CLIENT_ID, redirect_to, verifier, redirect_uri=SMITHERY_REDIRECT)
    )
    assert token.status_code == 200, token.text
    assert token.json()["access_token"].startswith("aigc_mcp_")

    (created,) = repository.created
    assert created["oauth_client_id"] == SMITHERY_CLIENT_ID
    assert created["client_label"] == "Smithery Connect"
    assert created["client_type"] == "other"
    assert created["expires_at"] is None
    # 预注册客户端不写进动态注册的客户端表
    assert repository.clients == {}


@pytest.mark.parametrize("path", ["/api/oauth/authorize/preview", "/api/oauth/authorize"])
def test_preregistered_clients_match_exactly_and_keep_their_redirects(path: str) -> None:
    client, _, _ = _app()
    _, challenge = _pkce()
    cases = [
        # 回调地址只认对方文档里登记的那一个
        (SMITHERY_CLIENT_ID, "https://evil.example/oauth/callback", "invalid_redirect_uri"),
        (SMITHERY_CLIENT_ID, REDIRECT, "invalid_redirect_uri"),
        # 不抓取文档：没登记的文档地址，以及协议、大小写、末尾斜杠不同的写法，都是未知客户端
        ("https://evil.example/.well-known/oauth-client", SMITHERY_REDIRECT, "invalid_client"),
        (SMITHERY_CLIENT_ID.replace("https://", "http://"), SMITHERY_REDIRECT, "invalid_client"),
        (SMITHERY_CLIENT_ID.replace("connect.", "CONNECT."), SMITHERY_REDIRECT, "invalid_client"),
        (SMITHERY_CLIENT_ID + "/", SMITHERY_REDIRECT, "invalid_client"),
    ]
    for client_id, redirect_uri, error in cases:
        body = _authorization(client_id, challenge, redirect_uri=redirect_uri)
        response = client.post(path, json={**body, "decision": "approve"})
        assert response.status_code == 400, body
        assert response.json()["error"] == error
        assert "redirect_to" not in response.json()


def test_preregistered_clients_still_need_pkce_and_a_registered_client_id_at_the_token_endpoint() -> None:
    client, repository, _ = _app()
    verifier, challenge = _pkce()
    plain = client.post(
        "/api/oauth/authorize",
        json={
            **_authorization(
                SMITHERY_CLIENT_ID, challenge, redirect_uri=SMITHERY_REDIRECT, code_challenge_method="plain"
            ),
            "decision": "approve",
        },
    )
    assert plain.json()["error"] == "invalid_request"
    assert plain.json()["redirect_to"].startswith(SMITHERY_REDIRECT + "?error=")

    redirect_to = _approve(client, SMITHERY_CLIENT_ID, challenge, redirect_uri=SMITHERY_REDIRECT)
    form = _code_form(SMITHERY_CLIENT_ID, redirect_to, verifier, redirect_uri=SMITHERY_REDIRECT)
    unknown = _exchange(client, {**form, "client_id": "https://evil.example/.well-known/oauth-client"})
    assert unknown.status_code == 401 and unknown.json()["error"] == "invalid_client"
    wrong_verifier = _exchange(client, {**form, "code_verifier": secrets.token_urlsafe(48)})
    assert wrong_verifier.status_code == 400 and wrong_verifier.json()["error"] == "invalid_grant"
    assert repository.created == []


def test_preregistered_client_entries_are_public_https_clients_that_fit_the_token_table() -> None:
    assert SMITHERY_CLIENT_ID in PREREGISTERED_CLIENTS
    for client_id, entry in PREREGISTERED_CLIENTS.items():
        assert client_id.startswith("https://")
        # 签发令牌时 client_id 写进 user_mcp_tokens.oauth_client_id VARCHAR(64)
        assert len(client_id) <= 64
        assert entry["redirect_uris"]
        for uri in entry["redirect_uris"]:
            validate_redirect_uri(uri)
            assert uri.startswith("https://")

    record = preregistered_client(SMITHERY_CLIENT_ID)
    assert record == {
        "client_id": SMITHERY_CLIENT_ID,
        "client_name": "Smithery Connect",
        "redirect_uris": [SMITHERY_REDIRECT],
        "token_endpoint_auth_method": "none",
        "client_secret_hash": None,
        "created_at": None,
        "last_authorized_at": None,
    }
    # 每次返回新字典，调用方改了也不影响登记表
    record["redirect_uris"].append("https://evil.example/cb")
    assert preregistered_client(SMITHERY_CLIENT_ID)["redirect_uris"] == [SMITHERY_REDIRECT]
    assert preregistered_client("aigc_oc_unknown") is None


def test_consent_endpoints_require_login_and_are_rate_limited_per_user() -> None:
    client, _, _ = _app(authenticated=False)
    for path in ("/api/oauth/authorize/preview", "/api/oauth/authorize"):
        response = client.post(path, json={"client_id": "x", "decision": "approve"})
        assert response.status_code == 401

    client, _, _ = _app()
    client_id = _register(client).json()["client_id"]
    _, challenge = _pkce()
    for _ in range(30):
        _approve(client, client_id, challenge)
    limited = client.post(
        "/api/oauth/authorize", json={**_authorization(client_id, challenge), "decision": "approve"}
    )
    assert limited.status_code == 429


def test_token_endpoint_fails_closed_without_redis() -> None:
    client, repository, app = _app()
    client_id = _register(client).json()["client_id"]
    verifier, challenge = _pkce()
    redirect_to = _approve(client, client_id, challenge)
    app.state.redis = None
    response = _exchange(client, _code_form(client_id, redirect_to, verifier))
    assert response.status_code == 503
    assert response.json()["error"] == "temporarily_unavailable"
    assert repository.created == []


def test_router_is_mounted_on_the_application() -> None:
    from backend.app.main import app

    paths = set(app.openapi()["paths"])
    assert {
        "/api/oauth/register",
        "/api/oauth/authorize/preview",
        "/api/oauth/authorize",
        "/api/oauth/token",
    } <= paths


def test_inferred_client_types_match_manual_token_client_types() -> None:
    # OAuth 签发的令牌和手动创建的令牌落同一张表，客户端类型取值必须一致
    names = ["Claude Code", "claude.ai", "Cursor", "Visual Studio Code", "VS Code", "MCP Inspector", ""]
    assert {infer_client_type(name) for name in names} == set(MCP_CLIENT_TYPES)
