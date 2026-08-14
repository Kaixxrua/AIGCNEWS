from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from backend.app.services.ingestion import github_hot_service as hot, github_project_metrics_service as metrics


class GitHubProjectMetricScoringTests(unittest.TestCase):
    metric_date = "2026-07-14"
    previous_date = "2026-07-13"

    def _compute(
        self, corroborated: set[str] | None = None, **overrides: object
    ) -> dict[str, object]:
        row = {
            "repo_id": "repo-1",
            "metric_date": self.metric_date,
            "stars": 1200,
            "forks": 120,
            "watchers": 20,
            "open_issues": 4,
            "repo_pushed_at": self.metric_date,
            "previous_snapshot_date": self.previous_date,
            "previous_stars": 1000,
            "previous_forks": 100,
            "previous_watchers": 10,
            "community_metrics_complete": 1,
            "previous_community_metrics_complete": 1,
            "trending_daily_star_growth": None,
            "baseline_7d": 10.0,
            "baseline_sample_count": 3,
        }
        row.update(overrides)
        repository = MagicMock()
        repository.get_github_daily_metric_inputs.return_value = [row]
        repository.upsert_github_daily_metrics.return_value = 1
        result = metrics.compute_github_daily_metrics(
            metric_date=self.metric_date,
            corroborated_repo_ids=corroborated,
            db=repository,
        )
        payload = repository.upsert_github_daily_metrics.call_args.args[0][0]
        return {"result": result, "payload": payload}

    def test_acceleration_curve_uses_log_ratio_interpolation(self) -> None:
        cases = (
            (0.125, 0.0),
            (0.25, 0.0),
            (0.375, 11.6993),
            (0.5, 20.0),
            (0.75, 31.6993),
            (1.0, 40.0),
            (1.5, 60.4737),
            (2.0, 75.0),
            (3.0, 89.6241),
            (4.0, 100.0),
            (8.0, 100.0),
        )
        baseline = 100.0
        for ratio, expected in cases:
            with self.subTest(ratio=ratio):
                daily_growth = ratio * (baseline + 1.0) - 1.0
                self.assertAlmostEqual(
                    metrics._growth_acceleration_curve(daily_growth, baseline),
                    expected,
                    places=4,
                )

    def test_non_positive_growth_has_no_acceleration(self) -> None:
        self.assertEqual(metrics._growth_acceleration_curve(0.0, 0.0), 0.0)
        self.assertEqual(metrics._growth_acceleration_curve(-1.0, 100.0), 0.0)

    def test_acceleration_confidence_scales_curve_score(self) -> None:
        scores = []
        for sample_count in (0, 1, 2, 3, 5):
            computed = self._compute(baseline_7d=0.0, baseline_sample_count=sample_count)
            scores.append(computed["payload"]["growth_acceleration_score"])

        self.assertEqual(scores[0], 0.0)
        self.assertAlmostEqual(scores[1], 100.0 / 3.0, places=4)
        self.assertAlmostEqual(scores[2], 200.0 / 3.0, places=4)
        self.assertEqual(scores[3], 100.0)
        self.assertEqual(scores[4], 100.0)

    def test_positive_growth_at_and_below_baseline_scores_smoothly(self) -> None:
        at_half_baseline = self._compute(
            stars=1050,
            baseline_7d=101.0,
            baseline_sample_count=3,
        )
        at_baseline = self._compute(
            stars=1100,
            baseline_7d=100.0,
            baseline_sample_count=3,
        )

        self.assertEqual(
            at_half_baseline["payload"]["growth_acceleration_score"],
            20.0,
        )
        self.assertEqual(
            at_baseline["payload"]["growth_acceleration_score"],
            40.0,
        )

    def test_growth_just_below_four_times_baseline_is_near_full_score(self) -> None:
        computed = self._compute(
            stars=1399,
            baseline_7d=100.0,
            baseline_sample_count=3,
        )

        self.assertAlmostEqual(
            computed["payload"]["growth_acceleration_score"],
            99.6411,
            places=4,
        )

    def test_zero_snapshot_growth_remains_zero_with_zero_baseline(self) -> None:
        computed = self._compute(
            stars=1000,
            baseline_7d=0.0,
            baseline_sample_count=3,
        )
        self.assertEqual(computed["payload"]["growth_acceleration_score"], 0.0)

    def test_complete_community_pair_scores_growth(self) -> None:
        computed = self._compute()
        payload = computed["payload"]
        self.assertEqual(payload["daily_fork_growth"], 20)
        self.assertEqual(payload["daily_watcher_growth"], 10)
        self.assertGreater(payload["community_engagement_score"], 0.0)

    def test_incomplete_community_pair_does_not_hide_exact_star_growth(self) -> None:
        for current, previous in ((0, 1), (1, 0), (None, 1), (1, None)):
            with self.subTest(current=current, previous=previous):
                computed = self._compute(
                    community_metrics_complete=current,
                    previous_community_metrics_complete=previous,
                )
                payload = computed["payload"]
                self.assertEqual(payload["daily_growth_source"], "snapshot_delta")
                self.assertEqual(payload["daily_star_growth"], 200)
                self.assertEqual(payload["daily_fork_growth"], 0)
                self.assertEqual(payload["daily_watcher_growth"], 0)
                self.assertEqual(payload["community_engagement_score"], 0.0)
                self.assertGreater(payload["hot_score"], 0.0)

    def test_trending_fallback_remains_available_without_community_score(self) -> None:
        computed = self._compute(
            previous_snapshot_date=None,
            previous_stars=0,
            trending_daily_star_growth=75,
            trending_daily_observed_at="2026-07-14T01:00:00+00:00",
        )
        payload = computed["payload"]
        self.assertEqual(payload["daily_growth_source"], "github_trending_daily")
        self.assertEqual(payload["daily_star_growth"], 75)
        self.assertEqual(payload["community_engagement_score"], 0.0)

    def test_gap_baseline_normalizes_growth_per_day(self) -> None:
        # 断供两天：基线为 3 天前（07-11），跨度增量按天归一，防虚高
        computed = self._compute(
            previous_snapshot_date="2026-07-11",
            previous_stars=1000,
            stars=1300,
            forks=130,
            previous_forks=100,
            watchers=40,
            previous_watchers=10,
        )
        payload = computed["payload"]
        self.assertEqual(payload["daily_growth_source"], "snapshot_delta_gap")
        self.assertEqual(payload["daily_star_growth"], 100)  # 300 // 3
        self.assertEqual(payload["daily_fork_growth"], 10)  # 30 // 3
        self.assertEqual(payload["daily_watcher_growth"], 10)  # 30 // 3
        # 记录真实基线日期而非假设的昨日
        self.assertEqual(payload["previous_snapshot_date"], "2026-07-11")
        self.assertEqual(payload["previous_stars"], 1000)
        result = computed["result"]
        self.assertEqual(result["gap_fallback"], 1)
        self.assertEqual(result["exact"], 0)
        self.assertEqual(result["available"], 1)
        self.assertEqual(result["positive_growth"], 1)
        self.assertGreater(payload["hot_score"], 0.0)

    def test_exact_baseline_reports_zero_gap_fallback(self) -> None:
        computed = self._compute()
        self.assertEqual(computed["payload"]["daily_growth_source"], "snapshot_delta")
        self.assertEqual(computed["payload"]["previous_snapshot_date"], self.previous_date)
        self.assertEqual(computed["result"]["gap_fallback"], 0)
        self.assertEqual(computed["result"]["exact"], 1)

    def test_gap_baseline_below_one_day_growth_floors_to_zero(self) -> None:
        # 跨度增量不足间隔天数时日增为 0（整除向下取整），但仍算有基线
        computed = self._compute(
            previous_snapshot_date="2026-07-11",
            previous_stars=1000,
            stars=1002,
        )
        payload = computed["payload"]
        self.assertEqual(payload["daily_growth_source"], "snapshot_delta_gap")
        self.assertEqual(payload["daily_star_growth"], 0)
        self.assertEqual(computed["result"]["available"], 1)

    def test_malformed_baseline_date_falls_back_to_unavailable(self) -> None:
        computed = self._compute(previous_snapshot_date="not-a-date")
        payload = computed["payload"]
        self.assertEqual(payload["daily_growth_source"], "unavailable")
        self.assertIsNone(payload["previous_snapshot_date"])
        self.assertEqual(computed["result"]["available"], 0)

    def test_recomputed_rows_use_v5(self) -> None:
        computed = self._compute()
        self.assertEqual(computed["payload"]["score_version"], "daily_hot_v5")
        self.assertEqual(computed["result"]["score_version"], "daily_hot_v5")

    def test_snapshot_payload_propagates_community_metrics_completeness(self) -> None:
        complete = metrics._snapshot_payload(
            {
                "repo_id": "repo-1",
                "full_name": "owner/repo",
                "community_metrics_complete": True,
            },
            metric_date=self.metric_date,
            captured_at="now",
        )
        incomplete = metrics._snapshot_payload(
            {"repo_id": "repo-1", "full_name": "owner/repo"},
            metric_date=self.metric_date,
            captured_at="now",
        )
        self.assertEqual(complete["community_metrics_complete"], 1)
        self.assertEqual(incomplete["community_metrics_complete"], 0)


class GitHubGrowthSuspicionTests(unittest.TestCase):
    """反作弊一二层打标：行为信号加和、佐证清零、留痕。"""

    metric_date = "2026-07-14"
    previous_date = "2026-07-13"

    def _compute(
        self, corroborated: set[str] | None = None, **overrides: object
    ) -> dict[str, object]:
        row = {
            "repo_id": "repo-1",
            "metric_date": self.metric_date,
            "stars": 1200,
            "forks": 120,
            "watchers": 20,
            "open_issues": 4,
            "repo_pushed_at": self.metric_date,
            "previous_snapshot_date": self.previous_date,
            "previous_stars": 1000,
            "previous_forks": 100,
            "previous_watchers": 10,
            "community_metrics_complete": 1,
            "previous_community_metrics_complete": 1,
            "trending_daily_star_growth": None,
            "baseline_7d": 10.0,
            "baseline_sample_count": 3,
        }
        row.update(overrides)
        repository = MagicMock()
        repository.get_github_daily_metric_inputs.return_value = [row]
        repository.upsert_github_daily_metrics.return_value = 1
        result = metrics.compute_github_daily_metrics(
            metric_date=self.metric_date,
            corroborated_repo_ids=corroborated,
            db=repository,
        )
        payload = repository.upsert_github_daily_metrics.call_args.args[0][0]
        return {"result": result, "payload": payload}

    def test_organic_growth_has_zero_suspicion(self) -> None:
        # 日增 200、fork 跟随率 10%、基线 10：无任何信号
        payload = self._compute()["payload"]
        self.assertEqual(payload["growth_suspicion_score"], 0.0)
        self.assertEqual(json.loads(payload["growth_suspicion_signals"]), [])
        self.assertFalse(payload["growth_corroborated"])

    def test_low_fork_follow_flags_when_pair_complete(self) -> None:
        # fork 零增长 + 日增 200 → 0% < 1% 阈值
        computed = self._compute(previous_forks=120)
        payload = computed["payload"]
        self.assertEqual(payload["growth_suspicion_score"], 0.4)
        self.assertEqual(
            json.loads(payload["growth_suspicion_signals"]), ["low_fork_follow"]
        )
        self.assertEqual(computed["result"]["suspicious"], 1)

    def test_low_fork_follow_skipped_when_pair_incomplete(self) -> None:
        # community pair 不完整时 fork 跟随率不可知，不得按 0 误伤
        payload = self._compute(
            previous_forks=120,
            community_metrics_complete=0,
        )["payload"]
        self.assertEqual(payload["growth_suspicion_score"], 0.0)
        self.assertEqual(json.loads(payload["growth_suspicion_signals"]), [])

    def test_spike_from_zero_baseline(self) -> None:
        payload = self._compute(baseline_7d=0.0)["payload"]
        self.assertEqual(payload["growth_suspicion_score"], 0.3)
        self.assertEqual(
            json.loads(payload["growth_suspicion_signals"]),
            ["spike_from_zero_baseline"],
        )

    def test_new_repo_surge(self) -> None:
        payload = self._compute(repo_created_at="2026-06-20")["payload"]
        self.assertEqual(payload["growth_suspicion_score"], 0.2)
        self.assertEqual(
            json.loads(payload["growth_suspicion_signals"]), ["new_repo_surge"]
        )

    def test_signals_compound(self) -> None:
        payload = self._compute(
            previous_forks=120,
            baseline_7d=0.0,
            repo_created_at="2026-06-20",
        )["payload"]
        self.assertAlmostEqual(payload["growth_suspicion_score"], 0.9, places=4)
        self.assertEqual(
            json.loads(payload["growth_suspicion_signals"]),
            ["low_fork_follow", "spike_from_zero_baseline", "new_repo_surge"],
        )

    def test_small_growth_never_flagged(self) -> None:
        # 日增 50 < 100 判定门槛，即使基线为 0
        payload = self._compute(stars=1050, baseline_7d=0.0)["payload"]
        self.assertEqual(payload["growth_suspicion_score"], 0.0)

    def test_corroboration_clears_score_but_keeps_signals(self) -> None:
        computed = self._compute(
            corroborated={"repo-1"},
            previous_forks=120,
            baseline_7d=0.0,
        )
        payload = computed["payload"]
        self.assertEqual(payload["growth_suspicion_score"], 0.0)
        self.assertTrue(payload["growth_corroborated"])
        self.assertEqual(
            json.loads(payload["growth_suspicion_signals"]),
            ["low_fork_follow", "spike_from_zero_baseline"],
        )
        self.assertEqual(computed["result"]["corroborated"], 1)

    def test_unavailable_growth_has_no_suspicion(self) -> None:
        payload = self._compute(
            previous_snapshot_date=None,
            trending_daily_star_growth=None,
        )["payload"]
        self.assertEqual(payload["growth_suspicion_score"], 0.0)
        self.assertEqual(json.loads(payload["growth_suspicion_signals"]), [])

    def test_corroboration_window_pads_one_day_each_side(self) -> None:
        since, until = metrics.corroboration_window("2026-08-14")
        self.assertEqual((since, until), ("2026-08-13", "2026-08-15"))


class GitHubTrendingSnapshotTests(unittest.TestCase):
    def test_daily_trending_snapshot_is_explicitly_incomplete(self) -> None:
        repository = MagicMock()
        repository.ensure_github_repo_candidate.return_value = "repo-1"
        repository.upsert_github_trending_hit.return_value = "repo-1"

        hot.record_github_trending_hits(
            [{"full_name": "owner/repo", "stars": 100, "period_star_growth": 5}],
            period="daily",
            observed_date="2026-07-14",
            captured_at="now",
            db=repository,
        )

        snapshot = repository.insert_github_repo_snapshot.call_args.args[0]
        self.assertEqual(snapshot["community_metrics_complete"], 0)


if __name__ == "__main__":
    unittest.main()
