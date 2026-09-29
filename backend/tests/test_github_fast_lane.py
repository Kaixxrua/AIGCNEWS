from __future__ import annotations

import asyncio
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.app.core import scheduler
from backend.app.services.ingestion import (
    github_fast_lane as fast_lane,
    github_project_enricher as enricher,
    github_project_metrics_service as metrics,
)


def _hit(full_name: str, stars: int, *, description: str = "demo") -> dict:
    return {
        "repo_id": full_name,
        "full_name": full_name,
        "description": description,
        "stars": stars,
        "source_channels": "daily_growth_observe_s300",
    }


class TargetMetricsTests(unittest.TestCase):
    def test_empty_targets_never_fall_through_to_full_recompute(self) -> None:
        with (
            patch.object(metrics, "_local_today", return_value=date(2026, 9, 29)),
            patch.object(metrics, "fetch_github_repo_metrics_batch") as fetch,
            patch.object(metrics, "compute_github_daily_metrics") as compute,
        ):
            result = metrics.refresh_and_compute_github_target_metrics(
                targets=[], min_stars=300, db=MagicMock()
            )

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["metric_date"], "2026-09-29")
        fetch.assert_not_called()
        compute.assert_not_called()

    def test_refreshes_and_recomputes_only_the_given_repos(self) -> None:
        db = MagicMock()
        outcome = SimpleNamespace(
            full_name="a/new",
            status="succeeded",
            metrics={"repo_id": "R_node", "full_name": "a/new", "stars": 900},
            observed_at="2026-09-29T05:00:00+00:00",
        )
        db.upsert_github_repo_metric_observations.return_value = 1
        corroborated = {"a/new"}
        with (
            patch.object(metrics, "_local_today", return_value=date(2026, 9, 29)),
            patch.object(
                metrics, "fetch_github_repo_metrics_batch", return_value=[outcome]
            ) as fetch,
            patch.object(
                metrics, "compute_github_daily_metrics", return_value={"rows": 1}
            ) as compute,
        ):
            result = metrics.refresh_and_compute_github_target_metrics(
                targets=[_hit("a/new", 900), _hit("A/New", 900)],
                min_stars=300,
                corroborated_repo_ids=corroborated,
                db=db,
            )

        fetch.assert_called_once_with(["a/new"])
        observations = db.upsert_github_repo_metric_observations.call_args.args[0]
        self.assertEqual(observations[0]["snapshot"]["snapshot_date"], "2026-09-29")
        # 既有 channel 标记保留，并追加日刷同款 daily_metrics
        self.assertEqual(
            observations[0]["candidate"]["source_channels"],
            "daily_growth_observe_s300,daily_metrics",
        )
        self.assertEqual(
            compute.call_args.kwargs,
            {
                "metric_date": "2026-09-29",
                "min_stars": 300,
                "repo_ids": ["a/new"],
                "corroborated_repo_ids": corroborated,
                "db": db,
            },
        )
        self.assertEqual(result["refresh"]["targets"], 1)
        self.assertEqual(result["refresh"]["snapshots"], 1)


class RunFastLaneTests(unittest.TestCase):
    def test_crawls_recent_window_and_snapshots_every_hit(self) -> None:
        ingestion = MagicMock()
        hits = [
            _hit("a/hot", 1115, description=""),
            _hit("a/quiet", 320, description=""),
            _hit("a/described", 800),
        ]
        crawl_summary = {
            "status": "success",
            "new_candidates": 1,
            "api_requests": 2,
            "upserted_candidates": hits,
            "new_repo_ids": ["a/hot"],
        }
        with (
            patch.object(fast_lane, "current_github_metric_date", return_value="2026-09-29"),
            patch.object(fast_lane, "crawl_github_search", return_value=crawl_summary) as crawl,
            patch.object(
                fast_lane,
                "refresh_and_compute_github_target_metrics",
                return_value={"refresh": {"targets": 3}, "metrics": {"rows": 3}},
            ) as refresh,
        ):
            summary = fast_lane.run_github_fast_lane(
                ingestion=ingestion, corroborated_repo_ids={"a/hot"}
            )

        kwargs = crawl.call_args.kwargs
        self.assertEqual(kwargs["min_stars"], enricher.GROWTH_OBSERVE_MIN_STARS)
        self.assertEqual(kwargs["created_start"], date(2026, 9, 22))
        self.assertEqual(kwargs["created_end"], date(2026, 9, 29))
        self.assertEqual(kwargs["channel"], enricher.GROWTH_OBSERVE_CHANNEL)
        # 新仓天然近期有 push，不加 pushed 过滤
        self.assertEqual(kwargs.get("pushed_after", ""), "")
        self.assertTrue(kwargs["collect_upserted"])
        self.assertIs(kwargs["ingestion"], ingestion)

        self.assertEqual(refresh.call_args.kwargs["targets"], hits)
        self.assertEqual(refresh.call_args.kwargs["min_stars"], 300)
        self.assertEqual(refresh.call_args.kwargs["corroborated_repo_ids"], {"a/hot"})

        self.assertEqual(summary["hits"], 3)
        self.assertEqual(summary["new_candidates"], 1)
        self.assertEqual(summary["new_repo_ids"], ["a/hot"])
        # 只有越过富化门槛且空描述的仓库需要先补 README
        self.assertEqual(summary["readme_candidates"], 1)
        self.assertNotIn("upserted_candidates", summary)


class FastLaneSchedulerJobTests(unittest.TestCase):
    def _run(self, lock: asyncio.Lock, **overrides):
        async def go():
            return await scheduler._run_github_fast_lane_job(
                repository=overrides.get("repository", MagicMock()),
                enrichment=overrides.get("enrichment", MagicMock()),
                semantic_sources=overrides.get("semantic_sources", MagicMock()),
                documents=None,
                github_lock=lock,
            )

        return asyncio.run(go())

    def test_yields_without_waiting_when_another_github_job_holds_the_lock(self) -> None:
        async def go():
            lock = asyncio.Lock()
            await lock.acquire()
            with patch.object(fast_lane, "run_github_fast_lane") as run:
                result = await scheduler._run_github_fast_lane_job(
                    repository=MagicMock(),
                    enrichment=MagicMock(),
                    github_lock=lock,
                )
            return result, run, lock

        result, run, lock = asyncio.run(go())
        self.assertTrue(result)
        run.assert_not_called()
        # 让路不得释放别人持有的锁
        self.assertTrue(lock.locked())

    def test_runs_discovery_then_enrichment_under_the_lock(self) -> None:
        lock = asyncio.Lock()
        order: list[str] = []

        def run(**kwargs):
            self.assertTrue(lock.locked())
            order.append("discover")
            return {"hits": 2, "new_candidates": 1, "readme_candidates": 1}

        def hydrate(semantic_sources):
            self.assertTrue(lock.locked())
            order.append("readme")
            return {"status": "success"}

        async def enrich(repository):
            self.assertTrue(lock.locked())
            order.append("enrich")
            return {"succeeded": 1}

        with (
            patch.object(fast_lane, "run_github_fast_lane", side_effect=run),
            patch.object(fast_lane, "hydrate_github_readmes", side_effect=hydrate),
            patch.object(scheduler, "_enrich_newly_eligible_github_projects", side_effect=enrich),
            patch.object(enricher, "github_enrichment_batch_running", return_value=False),
        ):
            result = self._run(lock)

        self.assertTrue(result)
        self.assertEqual(order, ["discover", "readme", "enrich"])
        self.assertFalse(lock.locked())

    def test_skips_readme_hydration_when_no_hit_needs_it(self) -> None:
        lock = asyncio.Lock()

        async def enrich(repository):
            return {}

        with (
            patch.object(
                fast_lane,
                "run_github_fast_lane",
                return_value={"hits": 1, "readme_candidates": 0},
            ),
            patch.object(fast_lane, "hydrate_github_readmes") as hydrate,
            patch.object(scheduler, "_enrich_newly_eligible_github_projects", side_effect=enrich) as top_up,
            patch.object(enricher, "github_enrichment_batch_running", return_value=False),
        ):
            self.assertTrue(self._run(lock))

        hydrate.assert_not_called()
        top_up.assert_called_once()

    def test_leaves_enrichment_to_a_batch_that_is_already_running(self) -> None:
        lock = asyncio.Lock()
        with (
            patch.object(
                fast_lane,
                "run_github_fast_lane",
                return_value={"hits": 1, "readme_candidates": 1},
            ),
            patch.object(fast_lane, "hydrate_github_readmes") as hydrate,
            patch.object(scheduler, "_enrich_newly_eligible_github_projects") as top_up,
            patch.object(enricher, "github_enrichment_batch_running", return_value=True),
        ):
            self.assertTrue(self._run(lock))

        hydrate.assert_not_called()
        top_up.assert_not_called()
        self.assertFalse(lock.locked())

    def test_discovery_failure_reports_failure_and_releases_lock(self) -> None:
        lock = asyncio.Lock()
        with (
            patch.object(fast_lane, "run_github_fast_lane", side_effect=RuntimeError("boom")),
            patch.object(scheduler, "_enrich_newly_eligible_github_projects") as top_up,
        ):
            self.assertFalse(self._run(lock))

        top_up.assert_not_called()
        self.assertFalse(lock.locked())

    def test_enrichment_failure_does_not_fail_the_round(self) -> None:
        lock = asyncio.Lock()

        async def enrich(repository):
            raise RuntimeError("model down")

        with (
            patch.object(
                fast_lane,
                "run_github_fast_lane",
                return_value={"hits": 1, "readme_candidates": 0},
            ),
            patch.object(scheduler, "_enrich_newly_eligible_github_projects", side_effect=enrich),
            patch.object(enricher, "github_enrichment_batch_running", return_value=False),
        ):
            self.assertTrue(self._run(lock))
        self.assertFalse(lock.locked())


class FastLaneShareTests(unittest.IsolatedAsyncioTestCase):
    """两小时指标刷新开窗期间快车道与之并行的契约。"""

    async def _run_shared(self, lock: asyncio.Lock, share: scheduler.GitHubFastLaneShare) -> bool:
        return await scheduler._run_github_fast_lane_job(
            repository=MagicMock(),
            enrichment=MagicMock(),
            semantic_sources=MagicMock(),
            github_lock=lock,
            fast_lane_share=share,
        )

    async def test_runs_alongside_refresh_while_window_is_open_without_enrichment(self) -> None:
        lock = asyncio.Lock()
        await lock.acquire()  # 刷新持锁
        share = scheduler.GitHubFastLaneShare()
        share.window.set()
        order: list[str] = []

        def run(**kwargs):
            self.assertTrue(share.participant.locked())
            order.append("discover")
            return {"hits": 1, "new_candidates": 1, "readme_candidates": 1}

        def hydrate(semantic_sources):
            self.assertTrue(share.participant.locked())
            order.append("readme")
            return {"status": "success"}

        with (
            patch.object(fast_lane, "run_github_fast_lane", side_effect=run),
            patch.object(fast_lane, "hydrate_github_readmes", side_effect=hydrate),
            patch.object(scheduler, "_enrich_newly_eligible_github_projects") as top_up,
            patch.object(enricher, "github_enrichment_batch_running", return_value=False),
        ):
            self.assertTrue(await self._run_shared(lock, share))

        self.assertEqual(order, ["discover", "readme"])
        # 富化批次留给刷新关窗后的补跑，避免两批并发
        top_up.assert_not_called()
        self.assertFalse(share.participant.locked())
        # 绝不释放刷新持有的 github 锁
        self.assertTrue(lock.locked())

    async def test_yields_when_refresh_holds_lock_but_window_is_closed(self) -> None:
        lock = asyncio.Lock()
        await lock.acquire()
        share = scheduler.GitHubFastLaneShare()
        with patch.object(fast_lane, "run_github_fast_lane") as run:
            self.assertTrue(await self._run_shared(lock, share))

        run.assert_not_called()
        self.assertTrue(lock.locked())
        self.assertFalse(share.participant.locked())

    async def test_yields_when_another_fast_lane_already_shares_the_window(self) -> None:
        lock = asyncio.Lock()
        await lock.acquire()
        share = scheduler.GitHubFastLaneShare()
        share.window.set()
        await share.participant.acquire()
        with patch.object(fast_lane, "run_github_fast_lane") as run:
            self.assertTrue(await self._run_shared(lock, share))

        run.assert_not_called()
        # 让路不得释放在途快车道持有的 participant
        self.assertTrue(share.participant.locked())

    async def test_shared_discovery_failure_releases_participant_only(self) -> None:
        lock = asyncio.Lock()
        await lock.acquire()
        share = scheduler.GitHubFastLaneShare()
        share.window.set()
        with patch.object(fast_lane, "run_github_fast_lane", side_effect=RuntimeError("boom")):
            self.assertFalse(await self._run_shared(lock, share))

        self.assertFalse(share.participant.locked())
        self.assertTrue(lock.locked())

    async def test_uncontended_run_keeps_using_the_github_lock(self) -> None:
        lock = asyncio.Lock()
        share = scheduler.GitHubFastLaneShare()

        def run(**kwargs):
            self.assertTrue(lock.locked())
            self.assertFalse(share.participant.locked())
            return {"hits": 1, "readme_candidates": 0}

        async def enrich(repository):
            return {}

        with (
            patch.object(fast_lane, "run_github_fast_lane", side_effect=run),
            patch.object(scheduler, "_enrich_newly_eligible_github_projects", side_effect=enrich) as top_up,
            patch.object(enricher, "github_enrichment_batch_running", return_value=False),
        ):
            self.assertTrue(await self._run_shared(lock, share))

        top_up.assert_called_once()
        self.assertFalse(lock.locked())

    async def test_closing_window_waits_for_in_flight_fast_lane(self) -> None:
        share = scheduler.GitHubFastLaneShare()
        order: list[str] = []
        finish = asyncio.Event()

        async def participant() -> None:
            async with share.participant:
                order.append("fast_lane_start")
                await finish.wait()
                order.append("fast_lane_done")

        async with scheduler._open_fast_lane_window(share):
            self.assertTrue(share.window.is_set())
            task = asyncio.create_task(participant())
            await asyncio.sleep(0)
            order.append("refresh_done")
            asyncio.get_running_loop().call_soon(finish.set)
        order.append("window_closed")
        await task

        self.assertFalse(share.window.is_set())
        self.assertEqual(
            order,
            ["fast_lane_start", "refresh_done", "fast_lane_done", "window_closed"],
        )

    async def test_window_closes_even_when_refresh_fails(self) -> None:
        share = scheduler.GitHubFastLaneShare()
        with self.assertRaises(RuntimeError):
            async with scheduler._open_fast_lane_window(share):
                raise RuntimeError("refresh failed")

        self.assertFalse(share.window.is_set())
        self.assertFalse(share.participant.locked())

    async def test_refresh_job_opens_window_only_while_fetching_snapshots(self) -> None:
        share = scheduler.GitHubFastLaneShare()
        seen: list[tuple[str, bool]] = []

        async def refresh(*args):
            seen.append(("refresh", share.window.is_set()))
            return {"refresh": {}}

        async def top_up(enrichment):
            seen.append(("top_up", share.window.is_set()))
            return {}

        with (
            patch.object(metrics, "current_github_metric_date", return_value="2026-09-29"),
            patch.object(scheduler, "_refresh_current_github_project_metrics", side_effect=refresh),
            patch.object(scheduler, "_enrich_newly_eligible_github_projects", side_effect=top_up),
        ):
            ok = await scheduler._run_github_project_metrics_refresh_job(
                repository=MagicMock(),
                enrichment=MagicMock(),
                fast_lane_share=share,
            )

        self.assertTrue(ok)
        self.assertEqual(seen, [("refresh", True), ("top_up", False)])

    async def test_startup_reconcile_opens_window_during_catch_up(self) -> None:
        share = scheduler.GitHubFastLaneShare()
        repo = MagicMock()
        repo.get_github_metric_refresh_status.return_value = {
            "target_count": 2,
            "snapshot_count": 1,
            "metric_count": 1,
        }
        seen: list[bool] = []

        async def refresh(*args):
            seen.append(share.window.is_set())
            return {}

        with (
            patch.object(metrics, "current_github_metric_date", return_value="2026-09-29"),
            patch.object(scheduler, "_refresh_current_github_project_metrics", side_effect=refresh),
        ):
            await scheduler._reconcile_current_github_project_metrics(
                repo,
                fast_lane_share=share,
            )

        self.assertEqual(seen, [True])
        self.assertFalse(share.window.is_set())


class MetricWriteLockTests(unittest.TestCase):
    def test_outcome_writes_and_daily_compute_share_one_write_lock(self) -> None:
        import threading

        entered = threading.Event()
        release = threading.Event()
        order: list[str] = []

        def slow_record(*args, **kwargs):
            order.append("record_start")
            entered.set()
            release.wait(timeout=5)
            order.append("record_done")
            return {}

        def compute(*args, **kwargs):
            order.append("compute")
            return {}

        with (
            patch.object(metrics, "_record_github_metric_outcomes", side_effect=slow_record),
            patch.object(metrics, "_compute_github_daily_metrics", side_effect=compute),
        ):
            writer = threading.Thread(
                target=metrics.record_github_metric_outcomes,
                kwargs={
                    "targets": [],
                    "outcomes": [],
                    "snapshot_date": "2026-09-29",
                    "captured_at": "2026-09-29T06:55:00+00:00",
                    "db": MagicMock(),
                },
            )
            writer.start()
            self.assertTrue(entered.wait(timeout=5))
            computer = threading.Thread(
                target=metrics.compute_github_daily_metrics,
                kwargs={"metric_date": "2026-09-29", "db": MagicMock()},
            )
            computer.start()
            computer.join(timeout=0.2)
            # 写入未完成前算分被写锁挡住
            self.assertTrue(computer.is_alive())
            release.set()
            writer.join(timeout=5)
            computer.join(timeout=5)

        self.assertEqual(order, ["record_start", "record_done", "compute"])


if __name__ == "__main__":
    unittest.main()
