from __future__ import annotations

"""Administrative cache invalidation for dashboard responses."""

import logging
from typing import Awaitable, Callable, Protocol

logger = logging.getLogger(__name__)


class AsyncCacheClient(Protocol):
    async def keys(self, pattern: str) -> list[bytes]: ...

    async def delete(self, *keys: bytes) -> int: ...


CacheClientFactory = Callable[[], AsyncCacheClient]
CacheClientCloser = Callable[[AsyncCacheClient], Awaitable[None]]


class DashboardCacheAdminService:
    """Clear all dashboard cache key variants and release the client."""

    def __init__(
        self,
        client_factory: CacheClientFactory,
        client_closer: CacheClientCloser,
        *,
        cache_prefix: str = "",
    ) -> None:
        self._client_factory = client_factory
        self._client_closer = client_closer
        self._cache_prefix = cache_prefix

    async def clear(self) -> int:
        client = self._client_factory()
        total_deleted = 0
        try:
            patterns = list(
                dict.fromkeys(
                    [
                        "aigc-cache:dashboard:*",
                        f"{self._cache_prefix}dashboard:*",
                        "dashboard:*",
                        "*:dashboard:*",
                    ]
                )
            )
            for pattern in patterns:
                keys = await client.keys(pattern)
                if keys:
                    await client.delete(*keys)
                    total_deleted += len(keys)
                    logger.info(
                        "[Ops] cache clear: pattern=%r 删除 %d keys",
                        pattern,
                        len(keys),
                    )
        finally:
            await self._client_closer(client)
        return total_deleted
