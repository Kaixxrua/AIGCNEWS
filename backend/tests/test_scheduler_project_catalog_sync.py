from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.core import scheduler


class ProjectCatalogSyncSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_job_runs_worker_off_event_loop(self) -> None:
        service = types.ModuleType("backend.app.services.project_catalog_sync")
        worker = MagicMock()
        worker.run_once.return_value = types.SimpleNamespace(
            claimed=1,
            processed=1,
            retried=0,
            dead=0,
        )
        service.ProjectCatalogSyncWorker = MagicMock(return_value=worker)

        with (
            patch.dict(sys.modules, {"backend.app.services.project_catalog_sync": service}),
            patch.object(
                scheduler.asyncio,
                "to_thread",
                new=AsyncMock(return_value=worker.run_once.return_value),
            ) as to_thread,
        ):
            await scheduler._run_project_catalog_sync_job()

        to_thread.assert_awaited_once_with(worker.run_once)

    def test_scheduler_registers_enabled_sync_job(self) -> None:
        fake_scheduler = MagicMock()
        fake_scheduler.running = False
        fake_scheduler.get_jobs.return_value = []

        with (
            patch.object(scheduler, "get_scheduler", return_value=fake_scheduler),
            patch("backend.app.core.config.settings.project_catalog_sync_worker_enabled", True),
            patch("backend.app.core.config.settings.project_catalog_sync_poll_seconds", 7),
            patch.object(scheduler.asyncio, "get_running_loop") as get_loop,
        ):
            get_loop.return_value.create_task.side_effect = lambda coroutine: coroutine.close()
            scheduler.start_scheduler()

        call = next(
            item
            for item in fake_scheduler.add_job.call_args_list
            if item.kwargs.get("id") == "project_catalog_sync"
        )
        self.assertEqual(call.kwargs["trigger"].interval.total_seconds(), 7)
        self.assertEqual(call.kwargs["max_instances"], 1)
        self.assertTrue(call.kwargs["coalesce"])


if __name__ == "__main__":
    unittest.main()
