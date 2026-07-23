from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.core import scheduler


class ProjectSemanticWarmupSchedulerTests(unittest.IsolatedAsyncioTestCase):
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

        with (
            patch.object(scheduler, "get_scheduler", return_value=fake_scheduler),
            patch("backend.app.core.config.settings.project_semantic_search_enabled", True),
            patch.object(scheduler.asyncio, "get_running_loop") as get_loop,
        ):
            get_loop.return_value.create_task.side_effect = lambda coroutine: coroutine.close()
            scheduler.start_scheduler()

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
