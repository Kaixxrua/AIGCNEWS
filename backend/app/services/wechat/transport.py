from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from backend.app.core.config import settings
from backend.app.services.outbound_target_policy import (
    OutboundTargetPolicyError,
    pin_http_target,
)
from backend.app.services.wechat.errors import (
    WeChatProxyError,
    WeChatRateLimited,
    WeChatUpstreamError,
)

logger = logging.getLogger(__name__)

WECHAT_BASE_URL = "https://mp.weixin.qq.com"
WECHAT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36 WAE/1.0"
)
WECHAT_HEADERS = {
    "User-Agent": WECHAT_USER_AGENT,
    "Referer": "https://mp.weixin.qq.com/",
    "Origin": "https://mp.weixin.qq.com",
    "Accept-Encoding": "identity",
    "Accept": "application/json, text/plain, */*",
}


@dataclass(frozen=True, slots=True)
class WeChatUpstreamResponse:
    status_code: int
    headers: httpx.Headers
    content: bytes
    cookies: dict[str, str]

    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        import json

        return json.loads(self.text())


def _extract_simple_cookies(set_cookie_headers: list[str]) -> dict[str, str]:
    """Extract name=value pairs from Set-Cookie headers, dropping attributes."""
    cookies: dict[str, str] = {}
    for raw in set_cookie_headers:
        # The first segment before ';' is the cookie-pair.
        pair = raw.split(";", 1)[0].strip()
        if not pair or "=" not in pair:
            continue
        name, _, value = pair.partition("=")
        cookies[name.strip()] = value.strip()
    return cookies


def _merge_cookie_dict(base: dict[str, str], update: dict[str, str]) -> dict[str, str]:
    """Merge new cookies over base, dropping EXPIRED values."""
    merged = dict(base)
    for name, value in update.items():
        if value == "EXPIRED":
            merged.pop(name, None)
        else:
            merged[name] = value
    return merged


def _build_cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


class WeChatMpTransport:
    """Fixed-target async HTTP transport for mp.weixin.qq.com.

    All target URLs are pinned server-side; no caller-supplied arbitrary URL
    is accepted. Secrets are passed in and out as cookie dictionaries so the
    transport itself remains stateless and testable.
    """

    def __init__(
        self,
        *,
        proxy: str | None = None,
        timeout_seconds: float | None = None,
        client_factory: Callable[..., httpx.AsyncClient] | None = None,
    ) -> None:
        self._proxy = proxy or None
        self._timeout = timeout_seconds or float(
            getattr(settings, "wechat_http_timeout_seconds", 15.0)
        )
        self._client_factory = client_factory or httpx.AsyncClient

    @staticmethod
    def _fixed_url(path: str, query: str = "") -> str:
        if query:
            return f"{WECHAT_BASE_URL}{path}?{query}"
        return f"{WECHAT_BASE_URL}{path}"

    def _client(self) -> httpx.AsyncClient:
        return self._client_factory(
            proxy=self._proxy,
            timeout=httpx.Timeout(self._timeout),
            follow_redirects=False,
            trust_env=False,
            headers=WECHAT_HEADERS,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        query: str = "",
        cookies: dict[str, str] | None = None,
        data: dict[str, Any] | None = None,
        content: bytes | None = None,
    ) -> WeChatUpstreamResponse:
        url = self._fixed_url(path, query)
        try:
            target = pin_http_target(url)
        except OutboundTargetPolicyError as exc:
            raise WeChatProxyError(str(exc)) from exc

        headers = dict(target.headers)
        if cookies:
            headers["Cookie"] = _build_cookie_header(cookies)

        request_kwargs: dict[str, Any] = {
            "method": method,
            "url": target.request_url,
            "headers": headers,
            "extensions": target.extensions,
        }
        if data is not None:
            request_kwargs["data"] = data
        if content is not None:
            request_kwargs["content"] = content

        client = self._client()
        try:
            response = await client.request(**request_kwargs)
        except httpx.ProxyError as exc:
            raise WeChatProxyError("代理连接失败") from exc
        except httpx.TimeoutException as exc:
            raise WeChatUpstreamError("微信上游请求超时") from exc
        except httpx.HTTPStatusError as exc:
            raise WeChatUpstreamError(
                f"微信上游返回 HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise WeChatUpstreamError(f"微信上游请求失败: {exc}") from exc
        finally:
            await client.aclose()

        if response.status_code == 429:
            raise WeChatRateLimited()

        set_cookie_headers: list[str] = []
        for value in response.headers.get_list("set-cookie"):
            set_cookie_headers.append(value)

        new_cookies = _extract_simple_cookies(set_cookie_headers)
        return WeChatUpstreamResponse(
            status_code=response.status_code,
            headers=response.headers,
            content=await response.aread(),
            cookies=new_cookies,
        )

    async def start_login(self, session_id: str) -> WeChatUpstreamResponse:
        data = {
            "userlang": "zh_CN",
            "redirect_url": "",
            "login_type": "3",
            "sessionid": session_id,
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        }
        return await self._request(
            "POST",
            "/cgi-bin/bizlogin",
            query="action=startlogin",
            data=data,
        )

    async def get_qr_code(self, random_value: str) -> WeChatUpstreamResponse:
        return await self._request(
            "GET",
            "/cgi-bin/scanloginqrcode",
            query=f"action=getqrcode&random={random_value}",
        )

    async def ask_scan_status(
        self,
        *,
        cookies: dict[str, str] | None = None,
    ) -> WeChatUpstreamResponse:
        return await self._request(
            "GET",
            "/cgi-bin/scanloginqrcode",
            query="action=ask&token=&lang=zh_CN&f=json&ajax=1",
            cookies=cookies,
        )

    async def biz_login(
        self,
        *,
        cookies: dict[str, str] | None = None,
    ) -> WeChatUpstreamResponse:
        data = {
            "userlang": "zh_CN",
            "redirect_url": "",
            "cookie_forbidden": "0",
            "cookie_cleaned": "0",
            "plugin_used": "0",
            "login_type": "3",
            "token": "",
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        }
        return await self._request(
            "POST",
            "/cgi-bin/bizlogin",
            query="action=login",
            cookies=cookies,
            data=data,
        )

    async def search_biz(
        self,
        *,
        keyword: str,
        token: str,
        cookies: dict[str, str],
        begin: int = 0,
        size: int = 5,
    ) -> WeChatUpstreamResponse:
        query = (
            f"action=search_biz&begin={begin}&count={size}"
            f"&query={httpx.QueryParams({'query': keyword})['query']}"
            f"&token={token}&lang=zh_CN&f=json&ajax=1"
        )
        return await self._request(
            "GET",
            "/cgi-bin/searchbiz",
            query=query,
            cookies=cookies,
        )

    async def appmsg_publish(
        self,
        *,
        fakeid: str,
        token: str,
        cookies: dict[str, str],
        begin: int = 0,
        size: int = 20,
        keyword: str = "",
    ) -> WeChatUpstreamResponse:
        params: dict[str, Any] = {
            "sub": "list" if not keyword else "search",
            "search_field": "null" if not keyword else "7",
            "begin": begin,
            "count": size,
            "query": keyword,
            "fakeid": fakeid,
            "type": "101_1",
            "free_publish_type": "1",
            "sub_action": "list_ex",
            "token": token,
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        }
        query = "&".join(
            f"{key}={httpx.QueryParams({key: value})[key]}"
            for key, value in params.items()
        )
        return await self._request(
            "GET",
            "/cgi-bin/appmsgpublish",
            query=query,
            cookies=cookies,
        )
