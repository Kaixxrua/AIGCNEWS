from __future__ import annotations

import json
import math
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

    def test_trend_confidence_blends_toward_neutral(self) -> None:
        # 日增 200 对零基线是 100 分趋势；样本不足时向中性 60 收敛而非归零
        scores = []
        for sample_count in (0, 1, 2, 3, 5):
            computed = self._compute(baseline_7d=0.0, baseline_sample_count=sample_count)
            scores.append(computed["payload"]["growth_acceleration_score"])

        self.assertEqual(scores[0], 60.0)
        self.assertAlmostEqual(scores[1], 60.0 + 40.0 / 3.0, places=3)
        self.assertAlmostEqual(scores[2], 60.0 + 80.0 / 3.0, places=3)
        self.assertEqual(scores[3], 100.0)
        self.assertEqual(scores[4], 100.0)

    def test_top_streak_only_discounts_heat_and_never_compounds_on_refresh(self) -> None:
        original = self._compute()["payload"]
        penalized = self._compute(previous_top_streak_days=5)["payload"]
        rerun = self._compute(previous_top_streak_days=5)["payload"]
        self.assertAlmostEqual(penalized["hot_score"], original["hot_score"] * 0.80, places=4)
        self.assertEqual(penalized["hot_score"], rerun["hot_score"])
        self.assertEqual(penalized["previous_top_streak_days"], 5)
        for key in ("daily_star_growth", "daily_growth_source", "growth_suspicion_score",
                    "scale_corrected_growth_score", "absolute_growth_score"):
            self.assertEqual(penalized[key], original[key])

    def test_growth_at_half_and_full_baseline_scores_smoothly(self) -> None:
        at_half_baseline = self._compute(stars=1050, baseline_7d=120.0)
        at_baseline = self._compute(stars=1100, baseline_7d=100.0)

        self.assertAlmostEqual(at_half_baseline["payload"]["growth_acceleration_score"], 20.0, places=4)
        self.assertAlmostEqual(at_baseline["payload"]["growth_acceleration_score"], 60.0, places=4)

    def test_zero_snapshot_growth_has_zero_heat(self) -> None:
        computed = self._compute(stars=1000, baseline_7d=0.0)
        payload = computed["payload"]
        self.assertEqual(payload["growth_acceleration_score"], 0.0)
        self.assertEqual(payload["hot_score"], 0.0)
        self.assertGreater(payload["maintenance_activity_score"], 0.0)

    def test_magnitude_decides_and_quality_only_modulates(self) -> None:
        # 增长 5 倍但趋势低、无社区信号的仓库，仍高于增长小但各项次要信号满分的仓库
        big = self._compute(
            stars=2000, baseline_7d=10000.0, community_metrics_complete=0,
            repo_pushed_at="2025-01-01",
        )["payload"]
        small = self._compute(
            stars=1200, baseline_7d=0.0, forks=300, watchers=100,
        )["payload"]
        self.assertGreater(big["hot_score"], small["hot_score"])

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
        self.assertEqual(payload["score_version"], "daily_hot_v11")

    def test_trending_fallback_shares_the_snapshot_scale(self) -> None:
        trending = self._compute(
            previous_snapshot_date=None,
            previous_stars=0,
            trending_daily_star_growth=200,
            community_metrics_complete=0,
        )["payload"]
        snapshot = self._compute(community_metrics_complete=0)["payload"]
        self.assertEqual(trending["daily_star_growth"], snapshot["daily_star_growth"])
        self.assertEqual(trending["hot_score"], snapshot["hot_score"])
        self.assertEqual(trending["score_version"], snapshot["score_version"])

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

    def test_missing_rate_history_scores_observed_growth_on_current_scale(self) -> None:
        computed = self._compute()
        payload = computed["payload"]
        self.assertEqual(payload["score_version"], "daily_hot_v11")
        self.assertEqual(computed["result"]["score_version"], "daily_hot_v11")
        self.assertEqual(computed["result"]["observed_velocity"], 1)
        self.assertEqual(computed["result"]["snapshot_velocity"], 0)
        self.assertAlmostEqual(
            payload["scale_corrected_growth_score"],
            100 * math.log1p(200 / math.sqrt(1000)) / math.log1p(100),
            places=3,
        )

    def test_unavailable_growth_scores_zero_on_current_version(self) -> None:
        computed = self._compute(previous_snapshot_date=None, trending_daily_star_growth=None)
        payload = computed["payload"]
        self.assertEqual(payload["daily_growth_source"], "unavailable")
        self.assertEqual(payload["score_version"], "daily_hot_v11")
        for key in (
            "hot_score",
            "scale_corrected_growth_score",
            "absolute_growth_score",
            "growth_acceleration_score",
            "community_engagement_score",
            "maintenance_activity_score",
        ):
            self.assertEqual(payload[key], 0.0, key)

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

    def test_unknown_baseline_is_not_zero_baseline(self) -> None:
        # 新入库仓库没有 3 天日增样本：无历史 ≠ 零基线，不得按脉冲打标
        for sample_count in (0, 1, 2):
            with self.subTest(sample_count=sample_count):
                payload = self._compute(
                    baseline_7d=0.0, baseline_sample_count=sample_count
                )["payload"]
                self.assertEqual(payload["growth_suspicion_score"], 0.0)
                self.assertEqual(json.loads(payload["growth_suspicion_signals"]), [])

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

    def test_single_signal_tags_without_demotion(self) -> None:
        computed = self._compute(previous_forks=120)
        self.assertEqual(computed["result"]["suspicious"], 1)
        self.assertEqual(computed["result"]["demoted"], 0)

    def test_multiple_signals_demote_heat(self) -> None:
        overrides = {"previous_forks": 120, "baseline_7d": 0.0, "repo_created_at": "2026-06-20"}
        suspicious = self._compute(**overrides)
        corroborated = self._compute(corroborated={"repo-1"}, **overrides)
        self.assertEqual(suspicious["result"]["demoted"], 1)
        self.assertEqual(corroborated["result"]["demoted"], 0)
        self.assertAlmostEqual(
            suspicious["payload"]["hot_score"],
            corroborated["payload"]["hot_score"] * (1 - 0.6 * 0.9),
            places=3,
        )
        # 降权不改动观测日增与排序过滤字段
        self.assertEqual(suspicious["payload"]["daily_star_growth"], 200)

    def _compute_rows(self, rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
        base = {
            "metric_date": self.metric_date,
            "stars": 1200,
            "forks": 120,
            "watchers": 20,
            "previous_snapshot_date": self.previous_date,
            "previous_stars": 1000,
            "previous_forks": 100,
            "previous_watchers": 10,
            "community_metrics_complete": 1,
            "previous_community_metrics_complete": 1,
            "baseline_7d": 10.0,
            "baseline_sample_count": 3,
        }
        repository = MagicMock()
        repository.get_github_daily_metric_inputs.return_value = [{**base, **row} for row in rows]
        metrics.compute_github_daily_metrics(metric_date=self.metric_date, db=repository)
        return {
            item["repo_id"]: item
            for item in repository.upsert_github_daily_metrics.call_args.args[0]
        }

    def test_coordinated_creation_across_accounts_demotes_alone(self) -> None:
        # 三个不同账号 5 分钟内建仓、同日暴涨：批量注册的诱饵仓
        payloads = self._compute_rows(
            [
                {"repo_id": "a", "full_name": "alpha/lure", "repo_created_at": "2026-06-13T12:04:01Z"},
                {"repo_id": "b", "full_name": "beta/lure", "repo_created_at": "2026-06-13",
                 "candidate_created_at": "2026-06-13T12:06:07Z"},
                {"repo_id": "c", "full_name": "gamma/lure", "repo_created_at": "2026-06-13T12:08:59Z"},
                {"repo_id": "d", "full_name": "delta/real", "repo_created_at": "2026-06-13T12:20:00Z"},
            ]
        )
        for repo_id in ("a", "b", "c"):
            self.assertEqual(
                json.loads(payloads[repo_id]["growth_suspicion_signals"]),
                ["coordinated_creation"],
            )
            self.assertEqual(payloads[repo_id]["growth_suspicion_score"], 0.6)
            self.assertLess(payloads[repo_id]["hot_score"], payloads["d"]["hot_score"])
        self.assertEqual(payloads["d"]["growth_suspicion_score"], 0.0)

    def test_coordinated_creation_sticks_after_a_prior_cluster(self) -> None:
        payloads = self._compute_rows(
            [
                {"repo_id": "a", "full_name": "alpha/lure", "prior_coordinated_creation": True},
                {"repo_id": "b", "full_name": "beta/lure", "prior_coordinated_creation": True,
                 "stars": 1050},
            ]
        )
        self.assertEqual(
            json.loads(payloads["a"]["growth_suspicion_signals"]), ["coordinated_creation"]
        )
        # 日增低于判定门槛时不打标
        self.assertEqual(json.loads(payloads["b"]["growth_suspicion_signals"]), [])

    def test_coordinated_creation_needs_distinct_owners_timestamps_and_surge(self) -> None:
        cases = {
            # 同一组织批量建仓是正常发布
            "same_owner": [
                {"repo_id": f"r{i}", "full_name": f"org/repo{i}", "repo_created_at": "2026-06-13T12:06:00Z"}
                for i in range(3)
            ],
            # 只有日期精度无法判定同一窗口
            "date_only": [
                {"repo_id": f"r{i}", "full_name": f"owner{i}/repo", "repo_created_at": "2026-06-13"}
                for i in range(3)
            ],
            # 日增不足判定门槛的不参与成簇
            "small_growth": [
                {"repo_id": f"r{i}", "full_name": f"owner{i}/repo", "stars": 1050,
                 "repo_created_at": "2026-06-13T12:06:00Z"}
                for i in range(3)
            ],
        }
        for name, rows in cases.items():
            with self.subTest(name):
                for payload in self._compute_rows(rows).values():
                    self.assertNotIn(
                        "coordinated_creation",
                        json.loads(payload["growth_suspicion_signals"]),
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


class GitHubQuarantineRefreshTests(unittest.TestCase):
    """疑似诱饵隔离名单挂在每轮热度指标落库之后重算。"""

    def _repository(self) -> MagicMock:
        repository = MagicMock()
        repository.get_github_daily_metric_inputs.return_value = [{
            "repo_id": "repo-1", "metric_date": "2026-07-14", "stars": 1200, "forks": 120,
            "watchers": 20, "previous_snapshot_date": "2026-07-13", "previous_stars": 1000,
            "previous_forks": 100, "previous_watchers": 10, "community_metrics_complete": 1,
            "previous_community_metrics_complete": 1, "baseline_7d": 10.0, "baseline_sample_count": 3,
        }]
        repository.upsert_github_daily_metrics.return_value = 1
        return repository

    def test_refresh_runs_after_metrics_are_stored(self) -> None:
        repository = self._repository()
        repository.refresh_github_quarantine.return_value = {"quarantined": 3, "added": 1, "released": 0}
        result = metrics.compute_github_daily_metrics(metric_date="2026-07-14", db=repository)
        calls = [name for name, _args, _kwargs in repository.mock_calls]
        # 嫌疑分与信号先落库，名单才按新指标重算
        self.assertLess(calls.index("upsert_github_daily_metrics"), calls.index("refresh_github_quarantine"))
        self.assertEqual(result["quarantine"], {"quarantined": 3, "added": 1, "released": 0})

    def test_refresh_failure_keeps_the_metrics_run_successful(self) -> None:
        repository = self._repository()
        repository.refresh_github_quarantine.side_effect = RuntimeError("lock timeout")
        with self.assertLogs(metrics.logger, level="WARNING") as logs:
            result = metrics.compute_github_daily_metrics(metric_date="2026-07-14", db=repository)
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["affected"], 1)
        self.assertIsNone(result["quarantine"])
        self.assertIn("沿用上一轮名单", logs.output[0])


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
