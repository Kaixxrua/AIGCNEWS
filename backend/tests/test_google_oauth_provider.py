from __future__ import annotations

import base64
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt

from backend.app.services.auth.oauth.contracts import OAuthProviderConfig
from backend.app.services.auth.oauth.providers.google import (
    DISCOVERY_URL,
    EXPECTED_ISSUER,
    GoogleOAuthError,
    GoogleOIDCProvider,
    GoogleTokenValidationError,
)


def _b64(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _provider(client: httpx.AsyncClient) -> GoogleOIDCProvider:
    return GoogleOIDCProvider(
        OAuthProviderConfig(name="google", client_id="client-id", client_secret="secret"),
        http_client=client,
    )


def test_authorization_url_uses_s256_pkce_and_nonce() -> None:
    provider = _provider(httpx.AsyncClient())
    query = parse_qs(urlparse(provider.authorization_url(
        state="state", redirect_uri="https://app.example/oauth/google/callback",
        code_verifier="verifier-abcdefghijklmnopqrstuvwxyz-0123456789", nonce="nonce",
    )).query)
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["state"] == ["state"]
    assert query["nonce"] == ["nonce"]
    assert query["scope"] == ["openid email profile"]


@pytest.mark.anyio
async def test_exchange_validates_discovery_exchange_jwks_and_nonce() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_numbers()
    nonce = "nonce-value"
    claims = {
        "iss": EXPECTED_ISSUER, "aud": "client-id", "sub": "google-sub",
        "email": "person@example.com", "email_verified": True, "nonce": nonce,
        "iat": int(time.time()), "exp": int(time.time()) + 300,
    }
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "key-1"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(DISCOVERY_URL):
            return httpx.Response(200, json={"issuer": EXPECTED_ISSUER, "token_endpoint": "https://oauth.example/token", "jwks_uri": "https://oauth.example/keys"})
        if str(request.url) == "https://oauth.example/token":
            assert b"code_verifier=verifier" in request.content
            return httpx.Response(200, json={"id_token": token})
        return httpx.Response(200, json={"keys": [{"kty": "RSA", "kid": "key-1", "n": _b64(public.n), "e": _b64(public.e)}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        identity = await _provider(client).exchange_code(code="code", redirect_uri="https://app.example/cb", code_verifier="verifier", nonce=nonce)
    assert identity.subject == "google-sub"
    assert identity.email == "person@example.com"


@pytest.mark.anyio
async def test_exchange_rejects_unverified_email_and_bad_nonce() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_numbers()
    claims = {"iss": EXPECTED_ISSUER, "aud": "client-id", "sub": "s", "email": "e@example.com", "email_verified": False, "nonce": "expected", "iat": int(time.time()), "exp": int(time.time()) + 300}
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k"})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(DISCOVERY_URL):
            return httpx.Response(200, json={"issuer": EXPECTED_ISSUER, "token_endpoint": "https://oauth.example/token", "jwks_uri": "https://oauth.example/keys"})
        if str(request.url).endswith("/token"):
            return httpx.Response(200, json={"id_token": token})
        return httpx.Response(200, json={"keys": [{"kty": "RSA", "kid": "k", "n": _b64(public.n), "e": _b64(public.e)}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(GoogleTokenValidationError):
            await _provider(client).exchange_code(code="c", redirect_uri="https://app.example/cb", code_verifier="v", nonce="expected")


@pytest.mark.anyio
async def test_exchange_rejects_non_https_metadata_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"issuer": EXPECTED_ISSUER, "token_endpoint": "http://localhost/token", "jwks_uri": "https://oauth.example/keys"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(GoogleOAuthError):
            await _provider(client).exchange_code(code="c", redirect_uri="https://app.example/cb", code_verifier="v", nonce="n")


def _exchange_handler(key, token: str):
    public = key.public_key().public_numbers()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url == httpx.URL(DISCOVERY_URL):
            return httpx.Response(200, json={"issuer": EXPECTED_ISSUER, "token_endpoint": "https://oauth.example/token", "jwks_uri": "https://oauth.example/keys"})
        if str(request.url).endswith("/token"):
            return httpx.Response(200, json={"id_token": token})
        return httpx.Response(200, json={"keys": [{"kty": "RSA", "kid": "k", "n": _b64(public.n), "e": _b64(public.e)}]})

    return handler


@pytest.mark.anyio
async def test_exchange_accepts_google_no_scheme_issuer_form() -> None:
    # Google 签发的 id_token iss 存在 "accounts.google.com"（无 scheme）形态，
    # 与 discovery 的严格 issuer 不同；官方客户端库两者皆收，拒绝它会误杀合法登录。
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims = {"iss": "accounts.google.com", "aud": "client-id", "sub": "s", "email": "e@example.com", "email_verified": True, "nonce": "n", "iat": int(time.time()), "exp": int(time.time()) + 300}
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(_exchange_handler(key, token))) as client:
        identity = await _provider(client).exchange_code(code="c", redirect_uri="https://app.example/cb", code_verifier="v", nonce="n")
    assert identity.subject == "s"


@pytest.mark.anyio
async def test_exchange_rejects_unknown_token_issuer() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    claims = {"iss": "https://evil.example.com", "aud": "client-id", "sub": "s", "email": "e@example.com", "email_verified": True, "nonce": "n", "iat": int(time.time()), "exp": int(time.time()) + 300}
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "k"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(_exchange_handler(key, token))) as client:
        with pytest.raises(GoogleTokenValidationError):
            await _provider(client).exchange_code(code="c", redirect_uri="https://app.example/cb", code_verifier="v", nonce="n")
