from __future__ import annotations

import httpx
import pytest

from backend.app.services.auth.oauth.providers.github import (
    GitHubOAuthProfileError,
    GitHubOAuthProvider,
    GitHubOAuthResponseError,
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
        "/user": httpx.Response(200, json={"id": 12345, "login": "octocat", "name": "Octo"}),
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
