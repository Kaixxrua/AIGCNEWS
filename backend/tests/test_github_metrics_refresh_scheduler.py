from __future__ import annotations

import asyncio
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

_config_name = "backend.app.core.config"
_repository_name = "backend.app.repositories.mysql_repo"
_previous_config = sys.modules.get(_config_name)
_previous_repository = sys.modules.get(_repository_name)
_config_stub = types.ModuleType(_config_name)
_config_stub.settings = MagicMock(scheduler_timezone="Asia/Shanghai")
_repository_stub = types.ModuleType(_repository_name)
_repository_stub.MySQLRepository = MagicMock
sys.modules[_config_name] = _config_stub
sys.modules[_repository_name] = _repository_stub
try:
    from backend.app.core import scheduler
    from backend.app.services.ingestion import github_project_metrics_service as metrics
finally:
    if _previous_config is None:
        sys.modules.pop(_config_name, None)
    else:
        sys.modules[_config_name] = _previous_config
    if _previous_repository is None:
        sys.modules.pop(_repository_name, None)
    else:
        sys.modules[_repository_name] = _previous_repository


class GitHubMetricDateTests(unittest.TestCase):
    def test_combined_refresh_passes_one_current_date_to_both_stages(self) -> None:
        with (
            patch.object(metrics, "_local_today", return_value=datetime(2026, 7, 14).date()),
            patch.object(
                metrics,
                "refresh_github_project_metric_snapshots",
                return_value={"status": "success"},
            ) as refresh,
            patch.object(
                metrics,
                "compute_github_daily_metrics",
                return_value={"status": "success"},
            ) as compute,
        ):
            result = metrics.refresh_and_compute_github_project_metrics(limit=80)

        self.assertEqual(result["metric_date"], "2026-07-14")
        self.assertEqual(refresh.call_args.kwargs["metric_date"], "2026-07-14")
        self.assertEqual(
            refresh.call_args.kwargs["_local_date"],
            datetime(2026, 7, 14).date(),
        )
        self.assertEqual(compute.call_args.kwargs["metric_date"], "2026-07-14")

    def test_live_snapshot_refresh_rejects_yesterday_before_database_access(self) -> None:
        with (
            patch.object(metrics, "_local_today", return_value=datetime(2026, 7, 14).date()),
            patch.object(metrics, "MySQLRepository") as repository,
            patch.object(metrics, "fetch_github_repo_metrics_batch") as fetch,
        ):
            with self.assertRaises(ValueError):
                metrics.refresh_github_project_metric_snapshots(
                    metric_date="2026-07-13"
                )

        repository.assert_not_called()
        fetch.assert_not_called()


class GitHubSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        scheduler._github_job_lock = None

    def test_refresh_status_decision_uses_coverage_and_freshness(self) -> None:
        now = datetime.now(timezone.utc)
        fresh = {
            "target_count": 2,
            "snapshot_count": 2,
            "metric_count": 2,
            "oldest_captured_at": now,
        }
        self.assertFalse(scheduler._github_refresh_needed(fresh))
        self.assertFalse(scheduler._github_refresh_needed({"target_count": 0}))
        self.assertTrue(
            scheduler._github_refresh_needed({**fresh, "snapshot_count": 1})
        )
        self.assertTrue(
            scheduler._github_refresh_needed(
                {
                    **fresh,
                    "oldest_captured_at": now - timedelta(hours=3),
                }
            )
        )

    async def test_startup_reconciliation_skips_fresh_complete_day(self) -> None:
        repo = MagicMock()
        repo.get_github_metric_refresh_status.return_value = {
            "target_count": 1,
            "snapshot_count": 1,
            "metric_count": 1,
            "oldest_captured_at": datetime.now(timezone.utc),
        }
        repository_module = types.ModuleType(_repository_name)
        repository_module.MySQLRepository = MagicMock(return_value=repo)
        with (
            patch.dict(sys.modules, {_repository_name: repository_module}),
            patch.object(
                metrics,
                "current_github_metric_date",
                return_value="2026-07-14",
            ),
            patch.object(
                scheduler,
                "_refresh_current_github_project_metrics",
                new=AsyncMock(),
            ) as refresh,
        ):
            await scheduler._reconcile_current_github_project_metrics()

        refresh.assert_not_awaited()

    async def test_startup_reconciliation_refreshes_only_today_when_incomplete(self) -> None:
        repo = MagicMock()
        repo.get_github_metric_refresh_status.return_value = {
            "target_count": 2,
            "snapshot_count": 1,
            "metric_count": 1,
            "oldest_captured_at": datetime.now(timezone.utc),
        }
        repository_module = types.ModuleType(_repository_name)
        repository_module.MySQLRepository = MagicMock(return_value=repo)
        with (
            patch.dict(sys.modules, {_repository_name: repository_module}),
            patch.object(
                metrics,
                "current_github_metric_date",
                return_value="2026-07-14",
            ),
            patch.object(
                scheduler,
                "_refresh_current_github_project_metrics",
                new=AsyncMock(return_value={}),
            ) as refresh,
        ):
            await scheduler._reconcile_current_github_project_metrics()

        refresh.assert_awaited_once_with("2026-07-14")
        repo.get_github_metric_refresh_status.assert_called_once_with(
            metric_date="2026-07-14",
            min_stars=500,
            limit=80,
        )

    async def test_github_jobs_share_one_lock(self) -> None:
        entered = 0
        maximum = 0

        async def body(_: str) -> dict[str, object]:
            nonlocal entered, maximum
            entered += 1
            maximum = max(maximum, entered)
            await asyncio.sleep(0.01)
            entered -= 1
            return {}

        with (
            patch(
                "backend.app.services.ingestion.github_project_metrics_service.current_github_metric_date",
                return_value="2026-07-14",
            ),
            patch.object(
                scheduler,
                "_refresh_current_github_project_metrics",
                side_effect=body,
            ),
        ):
            await asyncio.gather(
                scheduler._run_github_project_metrics_refresh_job(),
                scheduler._run_github_project_metrics_refresh_job(),
            )

        self.assertEqual(maximum, 1)

    def test_two_hour_job_avoids_daily_pipeline_hour(self) -> None:
        config = next(
            item
            for item in scheduler.SCHEDULE_CONFIG
            if item["id"] == "github_project_metrics_refresh"
        )
        self.assertEqual(config["cron"], {"hour": "1-23/2", "minute": 17})


if __name__ == "__main__":
    unittest.main()
