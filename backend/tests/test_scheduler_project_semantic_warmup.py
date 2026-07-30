from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.core import scheduler


class ProjectSemanticWarmupSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_job_calls_injected_warmup(self) -> None:
        warmup = MagicMock(return_value={"status": "success"})
        with patch.object(
            scheduler.asyncio,
            "to_thread",
            new=AsyncMock(return_value={"status": "success"}),
        ) as to_thread:
            await scheduler._run_project_semantic_warmup_job(warmup)

        to_thread.assert_awaited_once_with(warmup)

    async def test_job_calls_internal_warmup(self) -> None:
        service = types.ModuleType("backend.app.services.project_semantic_search")
        service.warmup_project_semantic_search = MagicMock(return_value={"status": "success"})

        with (
            patch.dict(sys.modules, {"backend.app.services.project_semantic_search": service}),
            patch.object(scheduler.asyncio, "to_thread", new=AsyncMock(return_value={"status": "success"})) as to_thread,
        ):
            await scheduler._run_project_semantic_warmup_job()

        to_thread.assert_awaited_once_with(service.warmup_project_semantic_search)

    def test_scheduler_registers_thirty_minute_warmup(self) -> None:
        fake_scheduler = MagicMock()
        fake_scheduler.running = False
        fake_scheduler.get_jobs.return_value = []

        runtime = scheduler.ApplicationSchedulerRuntime(
            MagicMock(),
            scheduler=fake_scheduler,
            semantic_search_enabled=True,
        )
        with patch.object(scheduler.asyncio, "get_running_loop") as get_loop:
            def close_coroutine(coroutine):
                coroutine.close()
                return MagicMock()

            get_loop.return_value.create_task.side_effect = close_coroutine
            runtime.start()

        call = next(
            item
            for item in fake_scheduler.add_job.call_args_list
            if item.kwargs.get("id") == "project_semantic_warmup"
        )
        self.assertEqual(call.kwargs["trigger"].interval.total_seconds(), 1800)
        self.assertEqual(call.kwargs["max_instances"], 1)
        self.assertTrue(call.kwargs["coalesce"])


if __name__ == "__main__":
    unittest.main()
