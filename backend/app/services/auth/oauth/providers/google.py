"""Google OpenID Connect provider with PKCE and nonce validation."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
from jose import JWTError, jwt

from backend.app.services.auth.oauth.contracts import OAuthProviderConfig

DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
EXPECTED_ISSUER = "https://accounts.google.com"
# Google 的 id_token iss 声明存在带/不带 scheme 两种形态（Google 官方客户端库
# 两者皆收），只认 discovery 的严格单值会把一批合法登录挡在回调里。
ACCEPTED_TOKEN_ISSUERS = (EXPECTED_ISSUER, "accounts.google.com")
_MAX_RESPONSE_BYTES = 1_048_576


class GoogleOAuthError(RuntimeError):
    """A bounded, non-sensitive failure communicating with Google."""


class GoogleTokenValidationError(GoogleOAuthError):
    """The token was not a valid Google OIDC identity token."""


@dataclass(frozen=True, slots=True)
class GoogleIdentity:
    subject: str
    email: str

    email_verified: bool
    name: str | None = None
    picture: str | None = None

    @property
    def provider_subject(self) -> str:
        return self.subject

    @property
    def username(self) -> str:
        return self.name or ""


class GoogleOIDCProvider:
    """Small Google OIDC client; callers persist state and bind it to the browser."""

    provider = "google"
    use_pkce = True
    use_nonce = True

    def __init__(
        self,
        config: OAuthProviderConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        if config.name != "google":
            raise ValueError("Google provider requires google configuration")
        if timeout <= 0 or timeout > 30:
            raise ValueError("Google upstream timeout is out of bounds")
        self.config = config
        self._client = http_client
        self._timeout = httpx.Timeout(timeout, connect=min(timeout, 5.0))

    def authorization_url(
        self, *, state: str, redirect_uri: str, code_verifier: str | None = None,
        code_challenge: str | None = None, nonce: str | None = None
    ) -> str:
        if not all((state, redirect_uri, nonce)) or not (code_verifier or code_challenge):
            raise ValueError("OAuth authorization parameters are required")
        challenge = code_challenge or _pkce_challenge(code_verifier or "")
        # The endpoint is obtained from discovery in exchange/validation; Google’s
        # stable endpoint is safe for the initial browser redirect.
        return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            {
                "client_id": self.config.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "openid email profile",
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "nonce": nonce,
                "access_type": "online",
            }
        )

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str | None, nonce: str | None
    ) -> GoogleIdentity:
        """Exchange a code and validate its OIDC identity token."""
        if not code or not code_verifier or not redirect_uri or not nonce:
            raise GoogleOAuthError("invalid OAuth callback")
        async with self._client_context() as client:
            discovery = await _get_json(client, DISCOVERY_URL)
            issuer = discovery.get("issuer")
            if issuer != EXPECTED_ISSUER:
                raise GoogleOAuthError("Google OIDC issuer mismatch")
            token_endpoint = _https_endpoint(discovery.get("token_endpoint"))
            jwks_uri = _https_endpoint(discovery.get("jwks_uri"))
            try:
                response = await client.post(
                    token_endpoint,
                    data={
                        "code": code,
                        "client_id": self.config.client_id,
                        "client_secret": self.config.client_secret,
                        "redirect_uri": redirect_uri,
                        "grant_type": "authorization_code",
                        "code_verifier": code_verifier,
                    },
                )
            except (httpx.HTTPError, TimeoutError) as exc:
                raise GoogleOAuthError("Google token exchange failed") from exc
            payload = _response_json(response)
            if response.status_code >= 400 or not isinstance(payload, dict):
                raise GoogleOAuthError("Google token exchange failed")
            id_token = payload.get("id_token")
            if not isinstance(id_token, str) or not id_token:
                raise GoogleOAuthError("Google response did not contain an identity token")
            # code flow 的响应必带 access_token；id_token 里的 at_hash 需要用
            # 它比对（OIDC 绑定校验），缺了 python-jose 会直接拒绝。
            access_token = payload.get("access_token")
            if access_token is not None and not isinstance(access_token, str):
                raise GoogleOAuthError("Google token exchange failed")
            jwks = await _get_json(client, jwks_uri)
            # discovery 的 issuer 已在上方严格校验；id_token 的 iss 按 Google
            # 官方双形态白名单校验，不再依赖 discovery 单值透传。
            return _validate_id_token(
                id_token, jwks,
                audience=self.config.client_id, nonce=nonce,
                access_token=access_token,
            )

    def _client_context(self):
        return _OwnedClient(self._client, self._timeout)


class _OwnedClient:
    def __init__(self, client: httpx.AsyncClient | None, timeout: httpx.Timeout) -> None:
        self.client, self.timeout, self.owned = client, timeout, client is None

    async def __aenter__(self):
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=self.timeout, follow_redirects=False)
        return self.client

    async def __aexit__(self, *args):
        if self.owned and self.client is not None:
            await self.client.aclose()


async def _get_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    try:
        response = await client.get(url)
    except (httpx.HTTPError, TimeoutError) as exc:
        raise GoogleOAuthError("Google OIDC discovery failed") from exc
    payload = _response_json(response)
    if response.status_code >= 400 or not isinstance(payload, dict):
        raise GoogleOAuthError("Google OIDC discovery failed")
    return payload


def _response_json(response: httpx.Response) -> Any:
    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise GoogleOAuthError("Google response exceeded size limit")
    try:
        return response.json()
    except (ValueError, UnicodeDecodeError) as exc:
        raise GoogleOAuthError("Google returned invalid JSON") from exc


def _https_endpoint(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("https://") or len(value) > 2048:
        raise GoogleOAuthError("Google OIDC metadata contained an invalid endpoint")
    return value


def _pkce_challenge(verifier: str) -> str:
    return _base64url(hashlib.sha256(verifier.encode("ascii")).digest())


def _base64url(value: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _validate_id_token(token: str, jwks: dict[str, Any], *, audience: str, nonce: str | None, access_token: str | None = None) -> GoogleIdentity:
    try:
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")
        keys = jwks.get("keys") if isinstance(jwks, dict) else None
        key = next((item for item in keys or [] if isinstance(item, dict) and item.get("kid") == kid), None)
        if key is None:
            raise GoogleTokenValidationError("Google signing key not found")
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=audience, issuer=ACCEPTED_TOKEN_ISSUERS, access_token=access_token, options={"require_exp": True, "require_iat": True, "require_sub": True})
    except (JWTError, GoogleTokenValidationError, TypeError, ValueError) as exc:
        if isinstance(exc, GoogleTokenValidationError):
            raise
        # python-jose 的底层消息是固定短语（Invalid audience/issuer、Signature
        # verification failed 等，已核查不含 token 内容），带进 reason 便于线上定位。
        raise GoogleTokenValidationError(
            f"Google identity token validation failed: {type(exc).__name__}: {exc}"
        ) from exc
    if nonce is not None and not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
        raise GoogleTokenValidationError("Google identity token nonce mismatch")
    if claims.get("email_verified") is not True:
        raise GoogleTokenValidationError("Google email is not verified")
    subject, email = claims.get("sub"), claims.get("email")
    if not isinstance(subject, str) or not subject or not isinstance(email, str) or not email:
        raise GoogleTokenValidationError("Google identity token lacks required identity claims")
    return GoogleIdentity(subject=subject, email=email, email_verified=True, name=_optional_str(claims.get("name")), picture=_optional_str(claims.get("picture")))


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
