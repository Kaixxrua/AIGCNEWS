from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class ApplicationOperationsRuntime:
    """Own administrator-triggered work for the application lifetime."""

    def __init__(self, *, shutdown_grace_seconds: float = 30.0) -> None:
        self._shutdown_grace_seconds = max(0.0, float(shutdown_grace_seconds))
        self._active_tasks: set[asyncio.Task[Any]] = set()
        self._stopping = False
        self._stop_lock = asyncio.Lock()

    async def _run(
        self,
        operation: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> None:
        try:
            if inspect.iscoroutinefunction(operation):
                await operation(*args, **kwargs)
            else:
                result = await asyncio.to_thread(operation, *args, **kwargs)
                if inspect.isawaitable(result):
                    await result
        except Exception:
            logger.exception(
                "Administrator operation failed: %s",
                getattr(operation, "__qualname__", type(operation).__name__),
            )

    def submit(
        self,
        operation: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        if self._stopping:
            return False
        task = asyncio.create_task(self._run(operation, args, kwargs))
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)
        return True

    async def stop(self) -> None:
        async with self._stop_lock:
            if self._stopping:
                return
            self._stopping = True
            tasks = tuple(self._active_tasks)
            if tasks:
                _, pending = await asyncio.wait(
                    tasks,
                    timeout=self._shutdown_grace_seconds,
                )
                if pending:
                    logger.warning(
                        "%d administrator operations exceeded the %.1f second "
                        "shutdown grace period; waiting to protect application resources.",
                        len(pending),
                        self._shutdown_grace_seconds,
                    )
                    await asyncio.gather(*pending, return_exceptions=True)
            self._active_tasks.clear()
