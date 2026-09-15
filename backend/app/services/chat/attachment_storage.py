"""In-memory storage for image attachments."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Dict, Optional, Tuple

IMAGE_TTL_SECONDS = 600
ImageEntry = Tuple[str, str, float]


class ImageCache:
    """Owner-agnostic in-memory cache for validated image payloads."""

    def __init__(
        self,
        *,
        ttl_seconds: int = IMAGE_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: Dict[str, ImageEntry] = {}
        self._lock = asyncio.Lock()

    async def put(self, attachment_id: str, base64_data: str, mime_type: str) -> float:
        now = self._clock()
        expires_at = now + self._ttl_seconds
        async with self._lock:
            expired = [
                key for key, (_, _, entry_expiry) in self._entries.items()
                if entry_expiry < now
            ]
            for key in expired:
                del self._entries[key]
            self._entries[attachment_id] = (base64_data, mime_type, expires_at)
        return expires_at

    async def get(self, attachment_id: str) -> Optional[Tuple[str, str]]:
        async with self._lock:
            entry = self._entries.get(attachment_id)
        if entry is None or self._clock() > entry[2]:
            return None
        return entry[0], entry[1]
