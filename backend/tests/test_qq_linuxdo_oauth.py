from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from backend.app.services.auth.oauth.contracts import OAuthProviderConfig
from backend.app.services.auth.oauth.providers._http import OAuthUpstreamError
from backend.app.services.auth.oauth.providers.linuxdo import LinuxDOOAuthProvider
from backend.app.services.auth.oauth.providers.qq import QQOAuthProvider

CALLBACK = "https://example.test/api/auth/oauth/{}/callback"
PROVIDERS = {"qq": QQOAuthProvider, "linuxdo": LinuxDOOAuthProvider}


def responses(provider):
    if provider == "qq":
        return [
            {"access_token": "access-token"},
            {"client_id": "app-id", "openid": "stable-openid"},
            {"ret": 0, "nickname": "Reader", "figureurl_qq_1": "https://q.qlogo.cn/avatar"},
        ]
    return [
        {"access_token": "access-token", "token_type": "Bearer"},
        {"id": 123, "username": "reader", "name": "Reader", "active": True,
         "avatar_template": "/user_avatar/linux.do/reader/{size}/1.png",
         "email": "untrusted@example.test", "email_verified": True, "api_key": "never-retain"},
    ]


@pytest.mark.parametrize("provider", PROVIDERS)
def test_authorize_preserves_state_and_callback_without_credentials(provider):
    adapter = PROVIDERS[provider](OAuthProviderConfig(provider, "app-id", "app-secret"))
    url = adapter.authorization_url(state="random-state", redirect_uri=CALLBACK.format(provider))
    params = parse_qs(urlsplit(url).query)
    assert params["client_id"] == ["app-id"]
    assert params["state"] == ["random-state"]
    assert params["response_type"] == ["code"]
    assert params["redirect_uri"] == [CALLBACK.format(provider)]
    assert params["scope"] == ["get_user_info" if provider == "qq" else "user"]
    assert "app-secret" not in url
    with pytest.raises(ValueError):
        adapter.authorization_url(state="", redirect_uri=CALLBACK.format(provider))


@pytest.mark.anyio
@pytest.mark.parametrize("provider", PROVIDERS)
async def test_exchange_uses_documented_endpoints_and_never_trusts_email(provider, caplog):
    caplog.set_level("INFO", logger="httpx")
    payloads, requests = responses(provider), []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payloads[len(requests) - 1])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = PROVIDERS[provider](OAuthProviderConfig(provider, "app-id", "app-secret"), http_client=client)
        profile = await adapter.exchange_code(code="code", redirect_uri=CALLBACK.format(provider))
    assert profile.provider_subject == ("stable-openid" if provider == "qq" else "123")
    assert profile.display_name == "Reader"
    assert profile.email is None and profile.email_verified is False
    assert "never-retain" not in repr(profile)
    assert "HTTP Request" in caplog.text
    assert "app-secret" not in caplog.text
    assert "access-token" not in caplog.text
    if provider == "qq":
        assert [r.url.path for r in requests] == ["/oauth2.0/token", "/oauth2.0/me", "/user/get_user_info"]
        assert all(r.url.host == "graph.qq.com" and r.method == "GET" for r in requests)
        assert requests[0].url.params["client_secret"] == "app-secret"
        assert requests[0].url.params["redirect_uri"] == CALLBACK.format(provider)
        assert all(r.url.params["fmt"] == "json" for r in requests[:2])
        assert requests[2].url.params["openid"] == "stable-openid"
        assert requests[2].url.params["oauth_consumer_key"] == "app-id"
    else:
        assert [r.url.path for r in requests] == ["/oauth2/token", "/api/user"]
        assert all(r.url.host == "connect.linux.do" for r in requests)
        assert requests[0].method == "POST"
        assert requests[0].headers["content-type"] == "application/x-www-form-urlencoded"
        form = parse_qs(requests[0].content.decode())
        assert form == {"grant_type": ["authorization_code"], "client_id": ["app-id"],
                        "client_secret": ["app-secret"], "code": ["code"],
                        "redirect_uri": [CALLBACK.format(provider)]}
        assert requests[1].headers["authorization"] == "Bearer access-token"
        assert "access-token" not in str(requests[1].url)
        assert profile.avatar_url == "https://linux.do/user_avatar/linux.do/reader/120/1.png"


@pytest.mark.anyio
@pytest.mark.parametrize("provider,index,payload", [
    ("qq", 0, {"error": 100, "error_description": "app-secret"}),
    ("qq", 0, {"access_token": ""}),
    ("qq", 1, {"client_id": "wrong-app", "openid": "attacker"}),
    ("qq", 1, {"client_id": "app-id", "openid": " "}),
    ("qq", 1, {"client_id": "app-id", "openid": 1}),
    ("qq", 2, {"ret": -1, "msg": "app-secret"}),
    ("qq", 2, {"nickname": "No success code"}),
    ("qq", 2, {"ret": False}),
    ("linuxdo", 0, {"error": "app-secret"}),
    ("linuxdo", 0, {"access_token": "injected\r\nheader"}),
    ("linuxdo", 0, {"access_token": "token", "token_type": "mac"}),
    ("linuxdo", 1, {"id": True}),
    ("linuxdo", 1, {"id": 0}),
    ("linuxdo", 1, {"id": -1}),
    ("linuxdo", 1, {"id": 1.5}),
    ("linuxdo", 1, {"id": "１２３"}),
    ("linuxdo", 1, {"id": "9" * 100}),
    ("linuxdo", 1, {"username": "mutable"}),
    ("linuxdo", 1, {"id": 123, "active": False}),
])
async def test_invalid_identity_claims_fail_closed(provider, index, payload):
    payloads = responses(provider)
    payloads[index] = payload
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=payloads[len(calls) - 1])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        adapter = PROVIDERS[provider](OAuthProviderConfig(provider, "app-id", "app-secret"), http_client=client)
        with pytest.raises(OAuthUpstreamError) as error:
            await adapter.exchange_code(code="code", redirect_uri=CALLBACK.format(provider))
    assert "app-secret" not in str(error.value)
    assert len(calls) == index + 1


@pytest.mark.anyio
@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("failure", ["redirect", "http", "json", "array", "size", "timeout"])
async def test_transport_is_bounded_and_never_follows_redirects(provider, failure):
    calls = []

    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("access-token app-secret", request=request)
        return {
            "redirect": httpx.Response(302, headers={"Location": "https://evil.test/"}),
            "http": httpx.Response(503, text="app-secret"),
            "json": httpx.Response(200, text="callback(app-secret)"),
            "array": httpx.Response(200, json=[]),
            "size": httpx.Response(200, content=b"x" * (2**20 + 1)),
        }[failure]

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
        adapter = PROVIDERS[provider](OAuthProviderConfig(provider, "app-id", "app-secret"), http_client=client)
        with pytest.raises(OAuthUpstreamError) as error:
            await adapter.exchange_code(code="code", redirect_uri=CALLBACK.format(provider))
    assert len(calls) == 1
    assert not any(secret in str(error.value) for secret in ("access-token", "app-secret"))
