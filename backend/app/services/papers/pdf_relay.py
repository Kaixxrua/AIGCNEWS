from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

import httpx


class PdfRelayUpstreamError(Exception):
    """上游 PDF 源返回非 200；路由层按原状态码映射为 HTTP 错误。"""

    def __init__(self, status_code: int, url: str) -> None:
        super().__init__(f"arxiv returned {status_code} for {url}")
        self.status_code = status_code
        self.url = url


class PdfRelay(Protocol):
    def stream(self, url: str, headers: dict[str, str]) -> AsyncIterator[bytes]: ...


class HttpxPdfRelay:
    """Stream a remote PDF without buffering it in application memory."""

    async def stream(
        self,
        url: str,
        headers: dict[str, str],
    ) -> AsyncIterator[bytes]:
        async with httpx.AsyncClient(follow_redirects=True, timeout=60.0) as client:
            async with client.stream("GET", url, headers=headers) as response:
                if response.status_code != 200:
                    raise PdfRelayUpstreamError(response.status_code, url)
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    yield chunk
