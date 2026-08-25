"""WeChat Open Platform website QR-login OAuth provider."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from backend.app.services.auth.oauth.contracts import OAuthProviderConfig

AUTHORIZATION_URL = "https://open.weixin.qq.com/connect/qrconnect"
TOKEN_URL = "https://api.weixin.qq.com/sns/oauth2/access_token"
USERINFO_URL = "https://api.weixin.qq.com/sns/userinfo"
_MAX_RESPONSE_BYTES = 1_048_576


class WeChatOAuthError(RuntimeError):
    """A bounded, non-sensitive failure communicating with WeChat."""


@dataclass(frozen=True, slots=True)
class WeChatIdentity:
    """Identity returned by WeChat website QR login.

    WeChat does not provide an email address through this flow.  Keeping the
    fields explicit prevents callers from accidentally treating a nickname as
    an email or as a verified claim.
    """

    subject: str
    email: str | None = None

    email_verified: bool = False
    name: str | None = None
    picture: str | None = None

    @property
    def provider_subject(self) -> str:
        return self.subject

    @property
    def username(self) -> str:
        return self.name or ""


class WeChatOAuthProvider:
    """Small client for WeChat Open Platform ``snsapi_login``."""

    provider = "wechat"
    use_pkce = False
    use_nonce = False

    def __init__(
        self,
        config: OAuthProviderConfig,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        if config.name != "wechat":
            raise ValueError("WeChat provider requires wechat configuration")
        if timeout <= 0 or timeout > 30:
            raise ValueError("WeChat upstream timeout is out of bounds")
        self.config = config
        self._client = http_client
        self._timeout = httpx.Timeout(timeout, connect=min(timeout, 5.0))

    def authorization_url(
        self, *, state: str, redirect_uri: str, code_challenge: str | None = None,
        nonce: str | None = None
    ) -> str:
        if not state or not redirect_uri:
            raise ValueError("OAuth authorization parameters are required")
        return AUTHORIZATION_URL + "?" + urlencode(
            {
                "appid": self.config.client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": "snsapi_login",
                "state": state,
            }
        ) + "#wechat_redirect"

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str | None = None,
        nonce: str | None = None
    ) -> WeChatIdentity:
        # redirect_uri is part of our local contract even though WeChat's token
        # endpoint does not consume it; requiring it prevents callback confusion.
        if not code or not redirect_uri:
            raise WeChatOAuthError("invalid OAuth callback")
        async with self._client_context() as client:
            token_response = await self._request(
                client,
                TOKEN_URL,
                params={
                    "appid": self.config.client_id,
                    "secret": self.config.client_secret,
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
            access_token = _required_str(token_response, "access_token")
            openid = _required_str(token_response, "openid")
            unionid = _optional_str(token_response.get("unionid"))
            userinfo = await self._request(
                client,
                USERINFO_URL,
                params={"access_token": access_token, "openid": openid, "lang": "zh_CN"},
            )
            subject = unionid or _optional_str(userinfo.get("unionid")) or openid
            if not subject:
                raise WeChatOAuthError("WeChat response lacked an identity subject")
            return WeChatIdentity(
                subject=subject,
                name=_optional_str(userinfo.get("nickname")),
                picture=_optional_str(userinfo.get("headimgurl")),
            )

    def _client_context(self) -> _OwnedClient:
        return _OwnedClient(self._client, self._timeout)

    async def _request(
        self, client: httpx.AsyncClient, url: str, *, params: dict[str, str]
    ) -> dict[str, Any]:
        try:
            response = await client.get(url, params=params)
        except (httpx.HTTPError, TimeoutError) as exc:
            raise WeChatOAuthError("WeChat upstream request failed") from exc
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise WeChatOAuthError("WeChat response exceeded size limit")
        try:
            payload = response.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise WeChatOAuthError("WeChat returned invalid JSON") from exc
        if response.status_code >= 400 or not isinstance(payload, dict):
            raise WeChatOAuthError("WeChat upstream request failed")
        if payload.get("errcode") not in (None, 0, "0"):
            raise WeChatOAuthError("WeChat upstream returned an error")
        return payload


class _OwnedClient:
    def __init__(self, client: httpx.AsyncClient | None, timeout: httpx.Timeout) -> None:
        self.client, self.timeout, self.owned = client, timeout, client is None

    async def __aenter__(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(timeout=self.timeout, follow_redirects=False)
        return self.client

    async def __aexit__(self, *args: Any) -> None:
        if self.owned and self.client is not None:
            await self.client.aclose()


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = _optional_str(payload.get(key))
    if not value:
        raise WeChatOAuthError("WeChat response lacked required identity data")
    return value


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
