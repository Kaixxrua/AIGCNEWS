"""Zero-disk, process-local screenshot cache boundary."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from typing import Dict, Optional, Tuple

SCREENSHOT_TTL_SECONDS = 300

ScreenshotEntry = Tuple[str, str, float]
ScreenshotPayload = Tuple[str, str]


class ScreenshotImageCache:
    """Store screenshot base64 payloads in process memory only."""

    def __init__(
        self,
        *,
        ttl_seconds: int = SCREENSHOT_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
        id_factory: Callable[[], object] = uuid.uuid4,
        entries: Dict[str, ScreenshotEntry] | None = None,
        lock: asyncio.Lock | None = None,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._id_factory = id_factory
        self._entries = entries if entries is not None else {}
        self._lock = lock if lock is not None else asyncio.Lock()

    async def put(self, image_base64: str, mime_type: str) -> str:
        image_id = str(self._id_factory())
        base64_data = image_base64
        if base64_data.startswith("data:"):
            base64_data = base64_data.split(",", 1)[-1]
        expires_at = self._clock() + self._ttl_seconds

        async with self._lock:
            await self._evict_expired()
            self._entries[image_id] = (base64_data, mime_type, expires_at)

        return image_id

    async def get(self, image_id: str) -> Optional[ScreenshotPayload]:
        async with self._lock:
            entry = self._entries.get(image_id)

        if entry is None or self._clock() > entry[2]:
            if entry is not None:
                async with self._lock:
                    self._entries.pop(image_id, None)
            return None

        return entry[0], entry[1]

    async def _evict_expired(self) -> None:
        now = self._clock()
        expired = [
            key
            for key, (_, _, expires_at) in self._entries.items()
            if expires_at < now
        ]
        for key in expired:
            del self._entries[key]
