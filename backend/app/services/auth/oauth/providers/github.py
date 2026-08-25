"""GitHub OAuth provider adapter.

The adapter intentionally contains no account or session policy.  It translates
GitHub's OAuth API into the small provider-neutral profile used by the auth
flow, while keeping credentials and upstream response bodies out of logs.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlencode

import httpx


class GitHubOAuthError(RuntimeError):
    """Base error raised for an unusable GitHub OAuth exchange."""


class GitHubOAuthTransportError(GitHubOAuthError):
    """The upstream request could not be completed safely."""


class GitHubOAuthResponseError(GitHubOAuthError):
    """GitHub returned an invalid, oversized, or unsuccessful response."""


class GitHubOAuthProfileError(GitHubOAuthError):
    """The GitHub account has no acceptable verified primary email."""


@dataclass(frozen=True, slots=True)
class OAuthProfile:
    provider: str
    subject: str
    email: str

    @property
    def provider_subject(self) -> str:
        return self.subject

    @property
    def email_verified(self) -> bool:
        return True
    username: str = ""
    display_name: str = ""


@dataclass(frozen=True, slots=True)
class GitHubOAuthConfig:
    client_id: str
    client_secret: str
    authorization_endpoint: str = "https://github.com/login/oauth/authorize"
    token_endpoint: str = "https://github.com/login/oauth/access_token"
    api_base_url: str = "https://api.github.com"


class GitHubOAuthProvider:
    """Protocol-compatible GitHub OAuth 2.0 + PKCE adapter."""

    provider = "github"
    use_pkce = True
    use_nonce = False
    _MAX_RESPONSE_BYTES = 1_048_576
    _TIMEOUT = httpx.Timeout(10.0, connect=5.0)
    _USER_AGENT = "AIGCNEWS-OAuth/1.0"

    def __init__(
        self,
        config: GitHubOAuthConfig | None = None,
        *,
        client_id: str = "",
        client_secret: str = "",
        client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    ) -> None:
        self.config = config or GitHubOAuthConfig(client_id, client_secret)
        self._client_factory = client_factory

    @staticmethod
    def create_code_verifier() -> str:
        """Return an RFC 7636 verifier suitable for a state payload."""
        return secrets.token_urlsafe(64)

    @staticmethod
    def _challenge(verifier: str) -> str:
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    def authorization_url(
        self,
        *,
        redirect_uri: str,
        state: str,
        code_verifier: str | None = None,
        code_challenge: str | None = None,
        nonce: str | None = None,
        scope: str = "read:user user:email",
    ) -> str:
        if not state or not redirect_uri or not (code_verifier or code_challenge):
            raise ValueError("redirect_uri, state, and code_verifier are required")
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": scope,
            "code_challenge": code_challenge or self._challenge(code_verifier or ""),
            "code_challenge_method": "S256",
        }
        return f"{self.config.authorization_endpoint}?{urlencode(params)}"

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str | None = None, nonce: str | None = None
    ) -> OAuthProfile:
        """Exchange a code and resolve the account's verified primary email."""
        if not code or not redirect_uri or not code_verifier:
            raise ValueError("code, redirect_uri, and code_verifier are required")
        token = await self._request_json(
            "POST",
            self.config.token_endpoint,
            data={
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
        )
        access_token = token.get("access_token")
        if not isinstance(access_token, str) or not access_token or len(access_token) > 8192:
            raise GitHubOAuthResponseError("GitHub token response was invalid")

        headers = {"Accept": "application/vnd.github+json", "Authorization": f"Bearer {access_token}"}
        user = await self._request_json("GET", f"{self.config.api_base_url}/user", headers=headers)
        emails = await self._request_json(
            "GET", f"{self.config.api_base_url}/user/emails", headers=headers
        )
        return self._profile(user, emails)

    async def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any] | list[Any]:
        try:
            async with self._client_factory(timeout=self._TIMEOUT, follow_redirects=False) as client:
                response = await client.request(method, url, **kwargs)
        except (httpx.HTTPError, TimeoutError) as exc:
            raise GitHubOAuthTransportError("GitHub OAuth request failed") from exc
        content_length = response.headers.get("content-length")
        if content_length and (not content_length.isdigit() or int(content_length) > self._MAX_RESPONSE_BYTES):
            raise GitHubOAuthResponseError("GitHub OAuth response was too large")
        if len(response.content) > self._MAX_RESPONSE_BYTES:
            raise GitHubOAuthResponseError("GitHub OAuth response was too large")
        if response.status_code < 200 or response.status_code >= 300:
            raise GitHubOAuthResponseError("GitHub OAuth upstream rejected the request")
        try:
            payload = response.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise GitHubOAuthResponseError("GitHub OAuth response was not JSON") from exc
        if not isinstance(payload, (dict, list)):
            raise GitHubOAuthResponseError("GitHub OAuth response had an invalid shape")
        return payload

    @classmethod
    def _profile(cls, user: dict[str, Any] | list[Any], emails: dict[str, Any] | list[Any]) -> OAuthProfile:
        if not isinstance(user, dict) or not isinstance(emails, list):
            raise GitHubOAuthResponseError("GitHub profile response had an invalid shape")
        subject = user.get("id")
        if isinstance(subject, bool) or not isinstance(subject, int) or subject <= 0:
            raise GitHubOAuthResponseError("GitHub profile did not contain a stable numeric subject")
        primary = next(
            (
                item for item in emails
                if isinstance(item, dict)
                and item.get("primary") is True
                and item.get("verified") is True
                and isinstance(item.get("email"), str)
                and item["email"].strip()
            ),
            None,
        )
        if primary is None:
            raise GitHubOAuthProfileError("GitHub account has no verified primary email")
        return OAuthProfile(
            provider="github",
            subject=str(subject),
            email=primary["email"].strip().lower(),
            username=str(user.get("login") or "")[:256],
            display_name=str(user.get("name") or "")[:256],
        )


GitHubOAuthAdapter = GitHubOAuthProvider
