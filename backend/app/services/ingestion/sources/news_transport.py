from __future__ import annotations

from typing import Any, Callable

import httpx

TECHMEME_RSS_URL = "https://www.techmeme.com/feed.xml"
TECHMEME_HOME_URL = "https://www.techmeme.com/"

_RSS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}
_HOME_HEADERS = {
    **_RSS_HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class TechmemeTransport:
    def __init__(
        self,
        client_factory: Callable[..., Any] = httpx.Client,
    ) -> None:
        self._client_factory = client_factory

    def fetch_rss(self) -> bytes:
        with self._client_factory(
            timeout=20,
            follow_redirects=True,
            headers=dict(_RSS_HEADERS),
        ) as client:
            response = client.get(TECHMEME_RSS_URL)
            response.raise_for_status()
            return response.content

    def fetch_homepage(self) -> str:
        with self._client_factory(
            timeout=20,
            follow_redirects=True,
            headers=dict(_HOME_HEADERS),
        ) as client:
            response = client.get(TECHMEME_HOME_URL)
            response.raise_for_status()
            return response.text
