from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

import httpx
from fastapi import HTTPException


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
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"arxiv returned {response.status_code} for {url}",
                    )
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    yield chunk
