from __future__ import annotations

import httpx
import pytest

from backend.app.services.auth.oauth.contracts import OAuthProviderConfig
from backend.app.services.auth.oauth.providers.wechat import (
    AUTHORIZATION_URL,
    WeChatOAuthError,
    WeChatOAuthProvider,
)


@pytest.fixture
def config() -> OAuthProviderConfig:
    return OAuthProviderConfig(name="wechat", client_id="wx-app", client_secret="secret")


def test_authorization_uses_open_platform_qr_login(config: OAuthProviderConfig) -> None:
    provider = WeChatOAuthProvider(config)
    url = provider.authorization_url(state="state", redirect_uri="https://site.test/cb")
    assert url.startswith(AUTHORIZATION_URL + "?")
    assert "scope=snsapi_login" in url
    assert "appid=wx-app" in url
    assert "#wechat_redirect" in url


@pytest.mark.anyio
async def test_exchange_prefers_unionid_and_never_invents_email(
    config: OAuthProviderConfig,
) -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "api.weixin.qq.com" and request.url.path.endswith("access_token"):
            assert request.url.params["secret"] == "secret"
            return httpx.Response(200, json={"access_token": "token", "openid": "open", "unionid": "union"})
        return httpx.Response(200, json={"openid": "open", "nickname": "N", "headimgurl": "https://img.test/a"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        identity = await WeChatOAuthProvider(config, http_client=client).exchange_code(
            code="code", redirect_uri="https://site.test/cb"
        )
    finally:
        await client.aclose()
    assert identity.subject == "union"
    assert identity.email is None
    assert identity.email_verified is False
    assert len(requests) == 2


@pytest.mark.anyio
async def test_exchange_falls_back_to_openid_and_bounds_upstream_errors(
    config: OAuthProviderConfig,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        # 无 unionid：identity 回退到 openid
        return httpx.Response(200, json={"access_token": "token", "openid": "open"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        identity = await WeChatOAuthProvider(config, http_client=client).exchange_code(
            code="code", redirect_uri="https://site.test/cb"
        )
    finally:
        await client.aclose()
    assert identity.subject == "open"
    assert identity.email is None

    # 上游错误体有界：超过大小上限的响应按失败处理
    async def oversized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{" + b"x" * (2**20) + b"}")

    big_client = httpx.AsyncClient(transport=httpx.MockTransport(oversized))
    try:
        with pytest.raises(WeChatOAuthError):
            await WeChatOAuthProvider(config, http_client=big_client).exchange_code(
                code="code", redirect_uri="https://site.test/cb"
            )
    finally:
        await big_client.aclose()


@pytest.mark.anyio
async def test_exchange_does_not_expose_upstream_error_or_credentials(
    config: OAuthProviderConfig,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errcode": 40029, "errmsg": "bad secret secret"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(WeChatOAuthError) as error:
            await WeChatOAuthProvider(config, http_client=client).exchange_code(
                code="code", redirect_uri="https://site.test/cb"
            )
    finally:
        await client.aclose()
    assert "secret" not in str(error.value)
    assert "40029" not in str(error.value)
