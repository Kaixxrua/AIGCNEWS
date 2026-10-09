"""QQ Connect website authorization-code login (JSON responses, OpenID identity)."""
from __future__ import annotations

import logging
from urllib.parse import urlencode

import httpx

from backend.app.services.auth.oauth.contracts import OAuthProfile, OAuthProviderConfig
from backend.app.services.auth.oauth.providers._http import (
    OAuthUpstreamError,
    optional_text,
    provider_client,
    request_json,
    required_text,
)

AUTHORIZATION_URL = "https://graph.qq.com/oauth2.0/authorize"
TOKEN_URL = "https://graph.qq.com/oauth2.0/token"
OPENID_URL = "https://graph.qq.com/oauth2.0/me"
USERINFO_URL = "https://graph.qq.com/user/get_user_info"


class _QQRequestLogFilter(logging.Filter):
    """HTTPX logs request URLs at INFO; QQ requires secrets in GET parameters."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                value.copy_with(query=None)
                if isinstance(value, httpx.URL) and value.host == "graph.qq.com"
                else value
                for value in record.args
            )
        return True


logging.getLogger("httpx").addFilter(_QQRequestLogFilter())


class QQOAuthProvider:
    use_pkce = False
    use_nonce = False

    def __init__(self, config: OAuthProviderConfig, *, http_client: httpx.AsyncClient | None = None):
        if config.name != "qq":
            raise ValueError("QQ provider requires qq configuration")
        self.config, self._client = config, http_client

    def authorization_url(
        self, *, state: str, redirect_uri: str,
        code_challenge: str | None = None, nonce: str | None = None,
    ) -> str:
        if not state or not redirect_uri:
            raise ValueError("OAuth authorization parameters are required")
        return AUTHORIZATION_URL + "?" + urlencode({
            "client_id": self.config.client_id, "response_type": "code",
            "redirect_uri": redirect_uri, "scope": "get_user_info", "state": state,
        })

    async def exchange_code(
        self, *, code: str, redirect_uri: str,
        code_verifier: str | None = None, nonce: str | None = None,
    ) -> OAuthProfile:
        if not code or not redirect_uri:
            raise OAuthUpstreamError("invalid OAuth callback")
        async with provider_client(self._client) as client:
            token = await request_json(client, "GET", TOKEN_URL, params={
                "grant_type": "authorization_code", "client_id": self.config.client_id,
                "client_secret": self.config.client_secret, "code": code,
                "redirect_uri": redirect_uri, "fmt": "json",
            })
            access_token = required_text(token, "access_token")
            identity = await request_json(client, "GET", OPENID_URL, params={
                "access_token": access_token, "fmt": "json",
            })
            if required_text(identity, "client_id") != self.config.client_id:
                raise OAuthUpstreamError("OAuth application identity mismatch")
            openid = required_text(identity, "openid", max_length=255)
            user = await request_json(client, "GET", USERINFO_URL, params={
                "access_token": access_token, "oauth_consumer_key": self.config.client_id,
                "openid": openid,
            })
            if type(user.get("ret")) is not int or user["ret"] != 0:
                raise OAuthUpstreamError("OAuth upstream returned an error")
            nickname = optional_text(user.get("nickname"))
            return OAuthProfile(
                provider_subject=openid, username=nickname, display_name=nickname,
                avatar_url=optional_text(user.get("figureurl_qq_2")) or optional_text(user.get("figureurl_qq_1")),
            )
