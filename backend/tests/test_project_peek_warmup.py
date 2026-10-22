from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.app.services.project_catalog import peek_warmup
from backend.app.services.project_catalog.peek_warmup import (
    WARMUP_INTERVAL,
    WARMUP_LIMIT,
    maintain_project_peek_cache,
    warm_project_peeks,
)


class ProjectPeekWarmupTests(unittest.IsolatedAsyncioTestCase):
    async def test_warms_default_hot_page_with_bounded_concurrency_and_deduplication(self) -> None:
        redis = SimpleNamespace(set=AsyncMock(return_value=True))
        items = [{"repo_id": f"acme/r{i}"} for i in range(WARMUP_LIMIT + 2)]
        catalog = SimpleNamespace(list_public_projects=AsyncMock(return_value=SimpleNamespace(
            result={"items": [items[0], {}, *items]},
        )))
        running = maximum = 0
        release = asyncio.Event()
        two_started = asyncio.Event()

        async def warm(repo_id, **kwargs):
            nonlocal running, maximum
            running += 1
            maximum = max(maximum, running)
            if running == 2:
                two_started.set()
            try:
                await release.wait()
                if repo_id == "acme/r0":
                    raise RuntimeError("one repository failed")
            finally:
                running -= 1

        peeks = SimpleNamespace(warm=AsyncMock(side_effect=warm))
        task = asyncio.create_task(warm_project_peeks(redis, peeks, catalog))
        await asyncio.wait_for(two_started.wait(), timeout=1)
        self.assertEqual(peeks.warm.await_count, 2)
        release.set()
        await task
        self.assertEqual(maximum, 2)
        self.assertEqual(peeks.warm.await_count, WARMUP_LIMIT)
        self.assertEqual(len({call.args[0] for call in peeks.warm.await_args_list}), WARMUP_LIMIT)
        catalog.list_public_projects.assert_awaited_once_with(
            scope="today", category="", subcategory="", q="", language="",
            page=1, page_size=WARMUP_LIMIT, sort="hot", user_id=None,
        )
        redis.set.assert_awaited_once_with("projects:peek:v1:warmup", b"1", nx=True, ex=WARMUP_INTERVAL)

    async def test_other_workers_do_not_repeat_warmup(self) -> None:
        redis = SimpleNamespace(set=AsyncMock(return_value=False))
        catalog, peeks = AsyncMock(), AsyncMock()
        await warm_project_peeks(redis, peeks, catalog)
        catalog.list_public_projects.assert_not_awaited()
        peeks.warm.assert_not_awaited()

    async def test_maintenance_starts_immediately_and_survives_a_failed_cycle(self) -> None:
        redis, peeks = object(), object()
        with (
            patch.object(peek_warmup, "ProjectCatalogQueryService") as catalog,
            patch.object(peek_warmup, "warm_project_peeks", side_effect=[RuntimeError("offline"), None]) as warm,
            patch.object(peek_warmup.asyncio, "sleep", side_effect=[None, asyncio.CancelledError]) as sleep,
        ):
            with self.assertRaises(asyncio.CancelledError):
                await maintain_project_peek_cache(redis, peeks)
        self.assertEqual(warm.await_count, 2)
        warm.assert_awaited_with(redis, peeks, catalog.return_value)
        self.assertEqual([call.args for call in sleep.await_args_list], [(WARMUP_INTERVAL,), (WARMUP_INTERVAL,)])
