from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.core import scheduler


class ProjectCatalogSyncSchedulerTests(unittest.TestCase):
    def test_scheduler_never_registers_or_starts_legacy_sync_job(self) -> None:
        fake_scheduler = MagicMock()
        fake_scheduler.running = False
        fake_scheduler.get_jobs.return_value = []

        runtime = scheduler.ApplicationSchedulerRuntime(
            MagicMock(),
            scheduler=fake_scheduler,
        )
        with patch.object(scheduler.asyncio, "get_running_loop") as get_loop:
            def close_coroutine(coroutine):
                coroutine.close()
                return MagicMock()

            get_loop.return_value.create_task.side_effect = close_coroutine
            runtime.start()

        job_ids = {
            item.kwargs.get("id")
            for item in fake_scheduler.add_job.call_args_list
        }
        self.assertNotIn("project_catalog_sync", job_ids)
        scheduled_coroutines = [
            item.args[0].cr_code.co_name
            for item in get_loop.return_value.create_task.call_args_list
        ]
        self.assertNotIn("_run_project_catalog_sync_job", scheduled_coroutines)
        self.assertFalse(hasattr(scheduler, "_run_project_catalog_sync_job"))


if __name__ == "__main__":
    unittest.main()
