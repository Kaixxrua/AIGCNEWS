from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from backend.app.monitoring.mcp_metrics_checkpoint import McpMetricsCheckpointRuntime


class McpMetricsCheckpointRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_restores_checkpoint_then_saves_redis_winner(self) -> None:
        saved = {"total_calls": 4149, "clients": {}, "tools": {}, "since": ""}
        current = {"total_calls": 4149, "clients": {}, "tools": {}, "since": ""}
        metrics = MagicMock()
        metrics.restore_if_newer = AsyncMock(return_value=True)
        metrics.snapshot = AsyncMock(return_value=current)
        repository = MagicMock()
        repository.load.return_value = saved
        repository.save_if_not_older.return_value = True
        runtime = McpMetricsCheckpointRuntime(metrics, repository)

        await runtime.restore_then_checkpoint()

        metrics.restore_if_newer.assert_awaited_once_with(saved)
        repository.save_if_not_older.assert_called_once_with(current)

    async def test_checkpoint_failure_does_not_break_startup(self) -> None:
        metrics = MagicMock()
        metrics.snapshot = AsyncMock(return_value={"total_calls": 1})
        repository = MagicMock()
        repository.load.side_effect = RuntimeError("database unavailable")
        runtime = McpMetricsCheckpointRuntime(metrics, repository)

        with self.assertLogs(
            "backend.app.monitoring.mcp_metrics_checkpoint", level="WARNING"
        ):
            await runtime.restore_then_checkpoint()

        metrics.snapshot.assert_not_awaited()
