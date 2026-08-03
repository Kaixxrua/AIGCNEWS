from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.services.ingestion import github_hot_service as hot
from backend.app.services.ingestion import github_project_metrics_service as metrics


class GitHubProjectMetricScoringTests(unittest.TestCase):
    metric_date = "2026-07-14"
    previous_date = "2026-07-13"

    def _compute(self, **overrides: object) -> dict[str, object]:
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
