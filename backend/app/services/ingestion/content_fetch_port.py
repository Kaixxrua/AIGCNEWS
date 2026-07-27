from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Protocol

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEFAULT_PAGE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}
DEFAULT_PAGE_TIMEOUT = 20


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
                follow_redirects=True,
                headers=self._headers,
                trust_env=True,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "html" not in content_type and "text" not in content_type:
                    return ""
                return self._clean_html(response.text)
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
