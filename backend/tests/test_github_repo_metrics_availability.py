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
            "watchers_count": 4,
            "open_issues_count": 1,
        }
        with self._client(lambda _request: httpx.Response(200, json=payload)) as client:
            result = fetch_github_repo_metrics("owner/repo", client=client, use_token=False)

        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.metrics["stars"], 12)

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
        repository.mark_github_repo_available.assert_called_once()
        repository.insert_github_repo_snapshot.assert_called_once()
        self.assertEqual(result["fetched"], 1)
        self.assertEqual(result["not_found_observations"], 1)
        self.assertEqual(result["newly_not_found"], 1)
        self.assertEqual(result["recovered"], 1)
        self.assertEqual(result["unknown"], 1)


if __name__ == "__main__":
    unittest.main()
