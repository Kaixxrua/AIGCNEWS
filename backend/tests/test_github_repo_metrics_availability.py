from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import httpx

from backend.app.services.ingestion import github_project_metrics_service as metrics
from backend.app.services.ingestion.source_github import (
    GitHubRepoMetricsResult,
    fetch_github_repo_metrics,
)


class GitHubRepoMetricsFetchTests(unittest.TestCase):
    def _client(self, handler):
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_success_returns_classified_metrics(self) -> None:
        payload = {
            "node_id": "repo-1",
            "full_name": "owner/repo",
            "html_url": "https://github.com/owner/repo",
            "stargazers_count": 12,
            "forks_count": 3,
            "watchers_count": 12,
            "subscribers_count": 4,
            "open_issues_count": 1,
        }
        with self._client(lambda _request: httpx.Response(200, json=payload)) as client:
            result = fetch_github_repo_metrics("owner/repo", client=client, use_token=False)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.metrics["stars"], 12)
        self.assertEqual(result.metrics["watchers"], 4)
        self.assertTrue(result.metrics["community_metrics_complete"])

    def test_search_shape_does_not_treat_watchers_count_as_subscribers(self) -> None:
        payload = {
            "node_id": "repo-1",
            "full_name": "owner/repo",
            "stargazers_count": 12,
            "watchers_count": 12,
        }
        with self._client(lambda _request: httpx.Response(200, json=payload)) as client:
            result = fetch_github_repo_metrics("owner/repo", client=client, use_token=False)

        self.assertEqual(result.metrics["watchers"], 0)
        self.assertFalse(result.metrics["community_metrics_complete"])

    def test_only_404_is_not_found(self) -> None:
        for status_code, expected in (
            (301, "unknown"),
            (403, "unknown"),
            (404, "not_found"),
            (429, "unknown"),
            (500, "unknown"),
        ):
            with self.subTest(status_code=status_code):
                with self._client(lambda _request, code=status_code: httpx.Response(code)) as client:
                    result = fetch_github_repo_metrics("owner/repo", client=client, use_token=False)
                self.assertEqual(result.status, expected)

    def test_transport_failure_is_unknown(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("proxy refused", request=request)

        with self._client(handler) as client:
            result = fetch_github_repo_metrics("owner/repo", client=client, use_token=False)

        self.assertEqual(result.status, "unknown")


class GitHubRepoAvailabilityRefreshTests(unittest.TestCase):
    def test_refresh_records_not_found_unknown_and_success(self) -> None:
        repository = MagicMock()
        repository.list_github_project_metric_targets.return_value = [
            {"repo_id": "missing", "full_name": "owner/missing", "availability_status": "active"},
            {"repo_id": "unknown", "full_name": "owner/unknown", "availability_status": "active"},
            {"repo_id": "live", "full_name": "owner/live", "availability_status": "not_found"},
        ]
        repository.record_github_repo_not_found.return_value = True
        repository.upsert_github_repo_metric_observations.return_value = 1
        outcomes = [
            GitHubRepoMetricsResult("owner/missing", "not_found", http_status=404),
            GitHubRepoMetricsResult("owner/unknown", "unknown", http_status=429),
            GitHubRepoMetricsResult(
                "owner/live",
                "succeeded",
                metrics={
                    "repo_id": "live",
                    "full_name": "owner/live",
                    "title": "owner/live",
                    "url": "https://github.com/owner/live",
                    "stars": 10,
                    "forks": 2,
                    "watchers": 3,
                    "open_issues": 1,
                },
                http_status=200,
            ),
        ]

        with (
            patch.object(metrics, "fetch_github_repo_metrics_batch", return_value=outcomes),
            patch.object(metrics, "_local_today", return_value=metrics.date(2026, 7, 23)),
        ):
            result = metrics.refresh_github_project_metric_snapshots(
                metric_date="2026-07-23",
                db=repository,
            )

        repository.record_github_repo_not_found.assert_called_once()
        repository.upsert_github_repo_metric_observations.assert_called_once()
        observations = repository.upsert_github_repo_metric_observations.call_args.args[0]
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["available_full_name"], "owner/live")
        self.assertEqual(observations[0]["candidate"]["full_name"], "owner/live")
        self.assertEqual(observations[0]["snapshot"]["full_name"], "owner/live")
        self.assertEqual(observations[0]["snapshot"]["snapshot_date"], "2026-07-23")
        # 批量写路径不再逐仓调用三个单行写方法
        repository.upsert_github_repo_candidate.assert_not_called()
        repository.mark_github_repo_available.assert_not_called()
        repository.insert_github_repo_snapshot.assert_not_called()
        self.assertEqual(result["fetched"], 1)
        self.assertEqual(result["updated_candidates"], 1)
        self.assertEqual(result["snapshots"], 1)
        self.assertEqual(result["not_found_observations"], 1)
        self.assertEqual(result["newly_not_found"], 1)
        self.assertEqual(result["recovered"], 1)
        self.assertEqual(result["unknown"], 1)

    def test_refresh_batch_write_failure_rolls_back_whole_batch(self) -> None:
        repository = MagicMock()
        repository.list_github_project_metric_targets.return_value = [
            {"repo_id": "one", "full_name": "owner/one", "availability_status": "not_found"},
            {"repo_id": "two", "full_name": "owner/two", "availability_status": "active"},
        ]
        repository.upsert_github_repo_metric_observations.side_effect = RuntimeError("db down")
        outcomes = [
            GitHubRepoMetricsResult(
                "owner/one",
                "succeeded",
                metrics={"repo_id": "one", "full_name": "owner/one", "stars": 10},
                http_status=200,
            ),
            GitHubRepoMetricsResult(
                "owner/two",
                "succeeded",
                metrics={"repo_id": "two", "full_name": "owner/two", "stars": 20},
                http_status=200,
            ),
        ]

        with (
            patch.object(metrics, "fetch_github_repo_metrics_batch", return_value=outcomes),
            patch.object(metrics, "_local_today", return_value=metrics.date(2026, 7, 23)),
        ):
            result = metrics.refresh_github_project_metric_snapshots(
                metric_date="2026-07-23",
                db=repository,
            )

        repository.upsert_github_repo_metric_observations.assert_called_once()
        # 整批回滚：不写部分成功，fetched 的两仓全部计入 skipped， recovered 不计
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["fetched"], 2)
        self.assertEqual(result["updated_candidates"], 0)
        self.assertEqual(result["snapshots"], 0)
        self.assertEqual(result["skipped"], 2)
        self.assertEqual(result["recovered"], 0)


if __name__ == "__main__":
    unittest.main()
