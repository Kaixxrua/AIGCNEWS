from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Protocol
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from backend.app.services.outbound_target_policy import pin_http_target

logger = logging.getLogger(__name__)

DEFAULT_PAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}
DEFAULT_PAGE_TIMEOUT = 20
# SSRF 防护：采集源 URL 可被投递为内网/云元数据地址（渗透实测）。
# 只允许标准端口并对每一跳重定向重新钉死公网 IP。
_ALLOWED_PORTS = {80, 443}
_MAX_REDIRECT_HOPS = 5
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class PageContentFetcher(Protocol):
    async def fetch(self, url: str, timeout: int = DEFAULT_PAGE_TIMEOUT) -> str: ...


class GitHubReadmeFetcher(Protocol):
    async def fetch(self, full_name: str) -> str: ...


def clean_html_text(html: str) -> str:
    """Extract readable text while preserving the current HTML-cleaning contract."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(
        [
            "script",
            "style",
            "nav",
            "header",
            "footer",
            "aside",
            "form",
            "button",
            "noscript",
            "iframe",
        ]
    ):
        tag.decompose()
    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


class DefaultPageContentFetcher:
    """Fetch page text with the legacy content-enricher HTTP behavior."""

    def __init__(
        self,
        headers: dict[str, str] | None = None,
        clean_html: Callable[[str], str] = clean_html_text,
    ) -> None:
        self._headers = headers if headers is not None else DEFAULT_PAGE_HEADERS
        self._clean_html = clean_html

    async def fetch(self, url: str, timeout: int = DEFAULT_PAGE_TIMEOUT) -> str:
        if not url or not url.startswith("http"):
            return ""
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                headers=self._headers,
                trust_env=True,
            ) as client:
                current_url = url
                for _ in range(_MAX_REDIRECT_HOPS + 1):
                    # 每一跳都重新解析并钉死公网 IP，请求发往 request_url，
                    # Host/SNI 保持原域名；私网/保留地址或非法端口在此被拒绝。
                    target = pin_http_target(current_url, allowed_ports=_ALLOWED_PORTS)
                    response = await client.get(
                        target.request_url,
                        headers=target.headers,
                        extensions=target.extensions,
                    )
                    if response.status_code in _REDIRECT_STATUSES:
                        location = response.headers.get("location")
                        if not location:
                            return ""
                        current_url = urljoin(target.logical_url, location)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if "html" not in content_type and "text" not in content_type:
                        return ""
                    return self._clean_html(response.text)
            logger.debug("[Enricher] 抓取页面重定向过多 %s", url)
            return ""
        except Exception as exc:
            logger.debug("[Enricher] 抓取页面失败 %s: %s", url, exc)
            return ""


class DefaultGitHubReadmeFetcher:
    """Fetch README text through the shared GitHub snapshot implementation."""

    async def fetch(self, full_name: str) -> str:
        if not full_name or "/" not in full_name:
            return ""
        try:
            from backend.app.services.ingestion.source_github import (
                fetch_github_readme_snapshot,
            )

            def fetch() -> str:
                with httpx.Client(
                    timeout=15,
                    follow_redirects=True,
                    trust_env=True,
                ) as client:
                    snapshot = fetch_github_readme_snapshot(
                        full_name,
                        client,
                        max_chars=20_000,
                    )
                    return snapshot.text if snapshot.status == "succeeded" else ""

            return await asyncio.to_thread(fetch)
        except Exception as exc:
            logger.debug("[Enricher] GitHub README 抓取失败 %s: %s", full_name, exc)
            return ""
