from __future__ import annotations

import asyncio
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.core import scheduler
from backend.app.services.ingestion import github_project_metrics_service as metrics


class GitHubMetricDateTests(unittest.TestCase):
    def test_combined_refresh_passes_one_current_date_to_both_stages(self) -> None:
        repository = MagicMock()
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
            result = metrics.refresh_and_compute_github_project_metrics(
                limit=80,
                db=repository,
            )

        self.assertEqual(result["metric_date"], "2026-07-14")
        self.assertEqual(refresh.call_args.kwargs["metric_date"], "2026-07-14")
        self.assertEqual(
            refresh.call_args.kwargs["_local_date"],
            datetime(2026, 7, 14).date(),
        )
        self.assertEqual(compute.call_args.kwargs["metric_date"], "2026-07-14")

    def test_live_snapshot_refresh_rejects_yesterday_before_database_access(self) -> None:
        repository = MagicMock()
        with (
            patch.object(metrics, "_local_today", return_value=datetime(2026, 7, 14).date()),
            patch.object(metrics, "fetch_github_repo_metrics_batch") as fetch,
        ):
            with self.assertRaises(ValueError):
                metrics.refresh_github_project_metric_snapshots(
                    metric_date="2026-07-13",
                    db=repository,
                )

        repository.list_github_project_metric_targets.assert_not_called()
        fetch.assert_not_called()


class GitHubSchedulerTests(unittest.IsolatedAsyncioTestCase):
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
            scheduler._github_refresh_needed({**fresh, "metric_count": 1})
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
        with (
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
            await scheduler._reconcile_current_github_project_metrics(repo)

        refresh.assert_not_awaited()

    async def test_startup_reconciliation_refreshes_only_today_when_incomplete(self) -> None:
        repo = MagicMock()
        repo.get_github_metric_refresh_status.return_value = {
            "target_count": 2,
            "snapshot_count": 1,
            "metric_count": 1,
            "oldest_captured_at": datetime.now(timezone.utc),
        }
        with (
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
            await scheduler._reconcile_current_github_project_metrics(repo)

        refresh.assert_awaited_once_with("2026-07-14", repo)
        repo.get_github_metric_refresh_status.assert_called_once_with(
            metric_date="2026-07-14",
            min_stars=300,
            limit=0,
        )

    async def test_scheduled_refresh_covers_all_eligible_projects(self) -> None:
        repository = MagicMock()
        service_module = types.ModuleType(
            "backend.app.services.ingestion.github_project_metrics_service"
        )
        refresh = MagicMock(return_value={})
        service_module.refresh_and_compute_github_project_metrics = refresh

        with patch.dict(
            sys.modules,
            {
                "backend.app.services.ingestion.github_project_metrics_service": service_module,
            },
        ):
            await scheduler._refresh_current_github_project_metrics(
                "2026-07-14",
                repository,
            )

        refresh.assert_called_once_with(
            min_stars=300,
            limit=0,
            metric_date="2026-07-14",
            db=repository,
        )

    async def test_hot_job_uses_configured_ingestion_repository(self) -> None:
        repository = MagicMock()
        service_module = types.ModuleType(
            "backend.app.services.ingestion.github_hot_service"
        )
        refresh = MagicMock()
        service_module.refresh_github_hot_candidates = refresh

        with patch.dict(
            sys.modules,
            {
                "backend.app.services.ingestion.github_hot_service": service_module,
            },
        ):
            await scheduler._run_github_hot_job(repository)

        refresh.assert_called_once_with(80, db=repository)

    async def test_enrichment_job_uses_configured_enrichment_repository(self) -> None:
        repository = MagicMock()
        service_module = types.ModuleType(
            "backend.app.services.ingestion.github_project_enricher"
        )
        enrich = MagicMock(return_value={"status": "success"})
        service_module.enrich_github_projects = enrich

        with patch.dict(
            sys.modules,
            {
                "backend.app.services.ingestion.github_project_enricher": service_module,
            },
        ):
            await scheduler._run_github_project_enrichment_job(repository)

        enrich.assert_called_once_with(limit=50, db=repository)

    async def test_github_jobs_share_one_lock(self) -> None:
        entered = 0
        maximum = 0

        async def body(_: str, __: object) -> dict[str, object]:
            nonlocal entered, maximum
            entered += 1
            maximum = max(maximum, entered)
            await asyncio.sleep(0.01)
            entered -= 1
            return {}

        lock = asyncio.Lock()
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
            repository = MagicMock()
            await asyncio.gather(
                scheduler._run_github_project_metrics_refresh_job(
                    repository=repository,
                    github_lock=lock,
                ),
                scheduler._run_github_project_metrics_refresh_job(
                    repository=repository,
                    github_lock=lock,
                ),
            )

        self.assertEqual(maximum, 1)


if __name__ == "__main__":
    unittest.main()
