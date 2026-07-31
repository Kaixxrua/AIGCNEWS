from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from backend.app.core.operations import ApplicationOperationsRuntime


def test_runtime_executes_sync_and_async_operations() -> None:
    async def run() -> None:
        runtime = ApplicationOperationsRuntime()
        events: list[str] = []

        def sync_operation(value: str) -> None:
            events.append(f"sync:{value}")

        async def async_operation(value: str) -> None:
            events.append(f"async:{value}")

        assert runtime.submit(sync_operation, "one")
        assert runtime.submit(async_operation, "two")
        await runtime.stop()

        assert sorted(events) == ["async:two", "sync:one"]
        assert runtime._active_tasks == set()
        assert not runtime.submit(sync_operation, "late")

    asyncio.run(run())


def test_runtime_waits_after_shutdown_grace_expires() -> None:
    async def run(warning: MagicMock) -> None:
        runtime = ApplicationOperationsRuntime(shutdown_grace_seconds=0.0)
        release = asyncio.Event()

        async def operation() -> None:
            await release.wait()

        assert runtime.submit(operation)
        stop_task = asyncio.create_task(runtime.stop())
        for _ in range(10):
            await asyncio.sleep(0)
            if warning.called:
                break

        warning.assert_called_once()
        assert not stop_task.done()
        release.set()
        await stop_task

    with patch("backend.app.core.operations.logger.warning") as warning:
        asyncio.run(run(warning))


def test_runtime_isolates_operation_failure() -> None:
    async def run() -> None:
        runtime = ApplicationOperationsRuntime()

        def operation() -> None:
            raise RuntimeError("failed")

        with patch("backend.app.core.operations.logger.exception") as exception:
            assert runtime.submit(operation)
            await runtime.stop()

        exception.assert_called_once()

    asyncio.run(run())
