from __future__ import annotations

from typing import Any
from unittest import IsolatedAsyncioTestCase

from fastapi import HTTPException

from backend.app.api import routes_ops_x_translation
from backend.app.models.schema_x_translation import XTranslationRetryRequest


class FakeRepository:
    def __init__(self, *, running: int = 0, retryable: int = 0, recovered: int = 0) -> None:
        self.running = running
        self.retryable = retryable
        self.recover_calls = 0
        self._recovered = recovered

    def recover_stale_running(self, stale_after_seconds: int = 900) -> int:
        self.recover_calls += 1
        self.running -= self._recovered
        return self._recovered

    def batch_running(self) -> int:
        return self.running

    def count_retryable(self, stale_after_seconds: int = 900) -> int:
        return self.retryable


class FakeOperations:
    def __init__(self, accepts: bool = True) -> None:
        self.accepts = accepts
        self.submitted: list[tuple[Any, int]] = []

    def submit(self, fn, limit: int) -> bool:
        self.submitted.append((fn, limit))
        return self.accepts


class XTranslationRetryRouteTest(IsolatedAsyncioTestCase):
    async def test_retry_recovers_stale_running_before_running_gate(self) -> None:
        # 两条 running 已过期：先回收再判断门禁，不应 409
        repository = FakeRepository(running=2, retryable=2, recovered=2)
        operations = FakeOperations()

        response = await routes_ops_x_translation.retry_x_translations(
            XTranslationRetryRequest(limit=50, concurrency=2),
            repository=repository,
            operations=operations,
        )

        self.assertEqual(repository.recover_calls, 1)
        self.assertEqual(response.status, "queued")
        self.assertEqual(response.result, {"retryable": 2, "limit": 50})
        self.assertEqual(len(operations.submitted), 1)

    async def test_retry_still_rejects_active_running_batch(self) -> None:
        # 租约仍有效的运行中批次：回收不掉，保持 409
        repository = FakeRepository(running=1, retryable=5, recovered=0)
        operations = FakeOperations()

        with self.assertRaises(HTTPException) as ctx:
            await routes_ops_x_translation.retry_x_translations(
                XTranslationRetryRequest(), repository=repository, operations=operations
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(operations.submitted, [])

    async def test_retry_noop_when_nothing_retryable(self) -> None:
        repository = FakeRepository(running=0, retryable=0)
        operations = FakeOperations()

        response = await routes_ops_x_translation.retry_x_translations(
            XTranslationRetryRequest(), repository=repository, operations=operations
        )

        self.assertEqual(response.status, "noop")
        self.assertEqual(operations.submitted, [])
