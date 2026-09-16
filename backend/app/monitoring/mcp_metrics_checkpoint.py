from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from backend.app.monitoring.mcp_redis_metrics import RedisMcpToolCallMetrics

logger = logging.getLogger(__name__)


class McpMetricsCheckpointRepository(Protocol):
    def load(self) -> dict | None: ...

    def save_if_not_older(self, snapshot: dict) -> bool: ...


class McpMetricsCheckpointRuntime:
    """Periodically checkpoints Redis metrics and restores them on cold start."""

    def __init__(
        self,
        metrics: RedisMcpToolCallMetrics,
        repository: McpMetricsCheckpointRepository,
        *,
        interval_seconds: float = 30.0,
    ) -> None:
        self._metrics = metrics
        self._repository = repository
        self._interval_seconds = max(1.0, float(interval_seconds))
        self._stop = asyncio.Event()

    async def restore_then_checkpoint(self) -> None:
        """Prefer the newer of Redis and PostgreSQL, then persist that winner."""
        try:
            saved = await asyncio.to_thread(self._repository.load)
            if saved is not None:
                restored = await self._metrics.restore_if_newer(saved)
                if restored:
                    logger.warning(
                        "[Startup] Restored MCP metrics from PostgreSQL checkpoint."
                    )
            await self.checkpoint_once()
        except Exception:
            logger.warning(
                "MCP metrics startup checkpoint failed (Redis remains authoritative)",
                exc_info=True,
            )

    async def checkpoint_once(self) -> bool:
        snapshot = await self._metrics.snapshot()
        return await asyncio.to_thread(
            self._repository.save_if_not_older,
            snapshot,
        )

    async def run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._interval_seconds,
                )
            except asyncio.TimeoutError:
                try:
                    await self.checkpoint_once()
                except Exception:
                    logger.warning(
                        "MCP metrics periodic PostgreSQL checkpoint failed",
                        exc_info=True,
                    )

    async def stop(self) -> None:
        self._stop.set()
        try:
            await self.checkpoint_once()
        except Exception:
            logger.warning(
                "MCP metrics final PostgreSQL checkpoint failed",
                exc_info=True,
            )
