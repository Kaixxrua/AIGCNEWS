from __future__ import annotations

import httpx
import pytest

from backend.app.services.auth.oauth.providers.github import (
    GitHubOAuthProfileError,
    GitHubOAuthProvider,
    GitHubOAuthResponseError,
    GitHubOAuthTransportError,
)


def provider(responses):
    def factory(**kwargs):
        return httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: responses[request.url.path]),
            **kwargs,
        )

    return GitHubOAuthProvider(client_id="client", client_secret="secret", client_factory=factory)


def test_authorization_url_uses_s256_pkce():
    adapter = GitHubOAuthProvider(client_id="client", client_secret="secret")
    url = adapter.authorization_url(
        redirect_uri="https://example.test/callback", state="state", code_verifier="v" * 64
    )
    assert "client_id=client" in url
    assert "code_challenge_method=S256" in url
    assert "code_challenge=" in url
    assert "state=state" in url


@pytest.mark.anyio
async def test_exchange_resolves_only_verified_primary_email():
    responses = {
        "/login/oauth/access_token": httpx.Response(200, json={"access_token": "token"}),
        "/user": httpx.Response(200, json={
            "id": 12345, "login": "octocat", "name": "Octo",
            "avatar_url": "https://avatars.githubusercontent.com/u/12345?v=4",
        }),
        "/user/emails": httpx.Response(
            200,
            json=[
                {"email": "unverified@example.test", "primary": True, "verified": False},
                {"email": "User@Example.Test", "primary": False, "verified": True},
                {"email": " Primary@Example.Test ", "primary": True, "verified": True},
            ],
        ),
    }
    profile = await provider(responses).exchange_code(
        code="code", redirect_uri="https://example.test/callback", code_verifier="v" * 64
    )
    assert profile.subject == "12345"
    assert profile.email == "primary@example.test"
    assert profile.username == "octocat"
    assert profile.display_name == "Octo"
    assert profile.avatar_url == "https://avatars.githubusercontent.com/u/12345?v=4"


@pytest.mark.anyio
async def test_exchange_rejects_missing_verified_primary_email():
    responses = {
        "/login/oauth/access_token": httpx.Response(200, json={"access_token": "token"}),
        "/user": httpx.Response(200, json={"id": 1}),
        "/user/emails": httpx.Response(200, json=[{"email": "a@b.test", "primary": True, "verified": False}]),
    }
    with pytest.raises(GitHubOAuthProfileError):
        await provider(responses).exchange_code(code="c", redirect_uri="r", code_verifier="v" * 64)


@pytest.mark.anyio
async def test_exchange_rejects_error_and_oversized_responses_without_logging_secrets():
    responses = {"/login/oauth/access_token": httpx.Response(500, text="secret-token")}
    with pytest.raises(GitHubOAuthResponseError):
        await provider(responses).exchange_code(code="c", redirect_uri="r", code_verifier="v" * 64)

    huge = {"/login/oauth/access_token": httpx.Response(200, content=b"{" + b"x" * (2**20) + b"}")}
    with pytest.raises(GitHubOAuthResponseError):
        await provider(huge).exchange_code(code="c", redirect_uri="r", code_verifier="v" * 64)


@pytest.mark.anyio
@pytest.mark.parametrize("failure_path,error", [
    ("/login/oauth/access_token", httpx.ConnectTimeout),
    ("/login/oauth/access_token", httpx.ProxyError),
    ("/user", httpx.ReadTimeout),
    ("/user/emails", httpx.ReadError),
])
async def test_exchange_recovers_from_transient_network_failure(failure_path, error):
    calls = {}
    bodies = {
        "/login/oauth/access_token": {"access_token": "token"},
        "/user": {"id": 123, "login": "octocat"},
        "/user/emails": [{"email": "user@example.test", "primary": True, "verified": True}],
    }

    def handler(request):
        path = request.url.path
        calls[path] = calls.get(path, 0) + 1
        if path == failure_path and calls[path] == 1:
            raise error("private-upstream-detail", request=request)
        if request.method == "POST":
            assert b"code_verifier=" in request.content
        else:
            assert request.headers["authorization"] == "Bearer token"
        return httpx.Response(200, json=bodies[path])

    adapter = GitHubOAuthProvider(client_id="client", client_secret="secret", client_factory=lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw))
    profile = await adapter.exchange_code(code="c", redirect_uri="https://app.example/cb", code_verifier="v" * 64)
    assert profile.subject == "123"
    assert calls == {path: 2 if path == failure_path else 1 for path in bodies}


@pytest.mark.anyio
@pytest.mark.parametrize("error,attempts", [
    (httpx.ConnectError, 2), (httpx.ReadTimeout, 1), (httpx.WriteError, 1),
    (httpx.RemoteProtocolError, 1), (httpx.ProxyError, 2),
])
async def test_token_transport_failure_is_bounded_and_redacted(error, attempts):
    calls = []

    def handler(request):
        calls.append(request)
        raise error("secret-code secret-token proxy-password", request=request)

    adapter = GitHubOAuthProvider(client_id="client", client_secret="secret", client_factory=lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw))
    with pytest.raises(GitHubOAuthTransportError) as caught:
        await adapter.exchange_code(code="secret-code", redirect_uri="https://app.example/cb", code_verifier="v" * 64)
    assert len(calls) == attempts
    assert str(caught.value) == f"GitHub OAuth request failed: stage=token error={error.__name__}"
