"""Linux DO Connect authorization-code login, keyed by immutable forum ID."""
from __future__ import annotations

from urllib.parse import urlencode, urljoin

import httpx

from backend.app.services.auth.oauth.contracts import OAuthProfile, OAuthProviderConfig
from backend.app.services.auth.oauth.providers._http import (
    OAuthUpstreamError,
    optional_text,
    provider_client,
    request_json,
    required_text,
)

AUTHORIZATION_URL = "https://connect.linux.do/oauth2/authorize"
TOKEN_URL = "https://connect.linux.do/oauth2/token"
USERINFO_URL = "https://connect.linux.do/api/user"


class LinuxDOOAuthProvider:
    use_pkce = False
    use_nonce = False

    def __init__(self, config: OAuthProviderConfig, *, http_client: httpx.AsyncClient | None = None):
        if config.name != "linuxdo":
            raise ValueError("Linux DO provider requires linuxdo configuration")
        self.config, self._client = config, http_client

    def authorization_url(
        self, *, state: str, redirect_uri: str,
        code_challenge: str | None = None, nonce: str | None = None,
    ) -> str:
        if not state or not redirect_uri:
            raise ValueError("OAuth authorization parameters are required")
        return AUTHORIZATION_URL + "?" + urlencode({
            "client_id": self.config.client_id, "response_type": "code",
            "redirect_uri": redirect_uri, "scope": "user", "state": state,
        })

    async def exchange_code(
        self, *, code: str, redirect_uri: str,
        code_verifier: str | None = None, nonce: str | None = None,
    ) -> OAuthProfile:
        if not code or not redirect_uri:
            raise OAuthUpstreamError("invalid OAuth callback")
        async with provider_client(self._client) as client:
            token = await request_json(client, "POST", TOKEN_URL, data={
                "grant_type": "authorization_code", "client_id": self.config.client_id,
                "client_secret": self.config.client_secret, "code": code,
                "redirect_uri": redirect_uri,
            }, headers={"Accept": "application/json"})
            access_token = required_text(token, "access_token")
            if optional_text(token.get("token_type")).lower() not in {"", "bearer"}:
                raise OAuthUpstreamError("OAuth upstream returned an invalid token type")
            user = await request_json(client, "GET", USERINFO_URL, headers={
                "Authorization": f"Bearer {access_token}", "Accept": "application/json",
            })
            # Names can change; never substitute username, email or external_ids.
            user_id = user.get("id")
            if not (
                type(user_id) is int or isinstance(user_id, str)
                and user_id.isascii() and user_id.isdigit()
            ) or len(str(user_id)) > 20 or int(user_id) <= 0:
                raise OAuthUpstreamError("OAuth response lacked required identity data")
            if user.get("active") is False:
                raise OAuthUpstreamError("OAuth upstream account is inactive")
            avatar = optional_text(user.get("avatar_template"))
            return OAuthProfile(
                provider_subject=str(int(user_id)),
                username=optional_text(user.get("username")),
                display_name=optional_text(user.get("name")),
                # Importer independently validates the CDN, never fetches arbitrary URLs.
                avatar_url=urljoin("https://linux.do/", avatar.replace("{size}", "120")) if avatar else "",
            )
