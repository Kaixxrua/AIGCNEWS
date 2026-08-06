"""Transport for the Sogou WeChat public index (weixin.sogou.com).

Direct connection by default: Sogou and mp.weixin.qq.com are domestic
targets, and routing them through an overseas datacenter proxy makes
anti-bot risk control worse, not better. All target URLs are pinned
server-side; no caller-supplied arbitrary URL is accepted.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

import httpx

from backend.app.core.config import settings
from backend.app.services.outbound_target_policy import (
    OutboundTargetPolicyError,
    pin_http_target,
)
from backend.app.services.wechat_sogou.errors import (
    SogouBlockedError,
    SogouUpstreamError,
)
from backend.app.services.wechat_sogou.parser import (
    extract_signed_url_from_redirect,
    is_antispider_content,
)

logger = logging.getLogger(__name__)

SOGOU_BASE_URL = "https://weixin.sogou.com"
SOGOU_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@dataclass(frozen=True, slots=True)
class SogouUpstreamResponse:
    status_code: int
    headers: httpx.Headers
    content: bytes
    cookies: dict[str, str]

    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


def _extract_simple_cookies(set_cookie_headers: list[str]) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for raw in set_cookie_headers:
        pair = raw.split(";", 1)[0].strip()
        if not pair or "=" not in pair:
            continue
        name, _, value = pair.partition("=")
        cookies[name.strip()] = value.strip()
    return cookies


def _build_cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


class SogouWechatTransport:
    """HTTP transport for Sogou WeChat search and article resolution.

    Holds a small cookie jar across calls: Sogou requires the SNUID/SUID
    cookies issued by the search page before it will resolve /link
    redirect URLs instead of bouncing to its antispider page.
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
            getattr(settings, "wechat_sogou_http_timeout_seconds", 15.0)
        )
        self._client_factory = client_factory or httpx.AsyncClient
        self._jar: dict[str, str] = {}

    def _client(self) -> httpx.AsyncClient:
        return self._client_factory(
            proxy=self._proxy,
            timeout=httpx.Timeout(self._timeout),
            follow_redirects=False,
            trust_env=False,
            headers={
                "User-Agent": SOGOU_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )

    async def _request(
        self,
        url: str,
        *,
        referer: str | None = None,
        use_jar: bool = False,
    ) -> SogouUpstreamResponse:
        try:
            target = pin_http_target(url)
        except OutboundTargetPolicyError as exc:
            raise SogouUpstreamError(str(exc)) from exc

        headers = dict(target.headers)
        if referer:
            headers["Referer"] = referer
        if use_jar and self._jar:
            headers["Cookie"] = _build_cookie_header(self._jar)

        client = self._client()
        try:
            response = await client.request(
                method="GET",
                url=target.request_url,
                headers=headers,
                extensions=target.extensions,
            )
        except httpx.TimeoutException as exc:
            raise SogouUpstreamError("搜狗微信请求超时") from exc
        except httpx.HTTPError as exc:
            raise SogouUpstreamError(f"搜狗微信请求失败: {exc}") from exc
        finally:
            await client.aclose()

        self._jar.update(_extract_simple_cookies(response.headers.get_list("set-cookie")))

        body = await response.aread()
        location = response.headers.get("location", "")
        if "antispider" in location:
            raise SogouBlockedError()
        return SogouUpstreamResponse(
            status_code=response.status_code,
            headers=response.headers,
            content=body,
            cookies=_extract_simple_cookies(response.headers.get_list("set-cookie")),
        )

    async def search_articles(
        self,
        keyword: str,
        *,
        page: int = 1,
    ) -> SogouUpstreamResponse:
        """Run a type=2 (article) search and return the raw results page."""
        query = httpx.QueryParams(
            {
                "type": "2",
                "s_from": "input",
                "query": keyword,
                "ie": "utf8",
                "page": str(page),
            }
        )
        response = await self._request(f"{SOGOU_BASE_URL}/weixin?{query}")
        if response.status_code != 200:
            raise SogouUpstreamError(f"搜狗微信搜索返回 HTTP {response.status_code}")
        if is_antispider_content(response.text()):
            raise SogouBlockedError()
        return response

    async def resolve_article_url(
        self,
        link_path: str,
        *,
        referer: str,
    ) -> str:
        """Resolve a Sogou /link redirect into the signed mp article URL."""
        if not link_path.startswith("/link?"):
            raise SogouUpstreamError("非法的搜狗文章跳转链接")
        response = await self._request(
            f"{SOGOU_BASE_URL}{link_path}",
            referer=referer,
            use_jar=True,
        )
        if response.status_code != 200:
            raise SogouBlockedError(
                f"搜狗文章跳转返回 HTTP {response.status_code}，可能触发反爬"
            )
        try:
            return extract_signed_url_from_redirect(response.text())
        except ValueError as exc:
            raise SogouUpstreamError("未能从搜狗跳转页提取文章链接") from exc

    async def fetch_article_page(self, url: str) -> SogouUpstreamResponse:
        """Fetch an mp.weixin.qq.com article page (signed URL allowed)."""
        if not url.startswith("https://mp.weixin.qq.com/"):
            raise SogouUpstreamError("非法的微信文章链接")
        response = await self._request(url)
        if response.status_code != 200:
            raise SogouUpstreamError(f"微信文章页返回 HTTP {response.status_code}")
        return response
