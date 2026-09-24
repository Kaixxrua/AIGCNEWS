from __future__ import annotations

import json
import re
import unittest
from unittest.mock import MagicMock, patch

import httpx

from backend.app.services.ingestion import github_project_metrics_service as metrics, source_github
from backend.app.services.ingestion.source_github import (
    GitHubRepoMetricsResult,
    _parse_graphql_repo,
    _parse_metrics_item,
    fetch_github_repo_metrics,
    fetch_github_repo_metrics_batch,
)


class LicenseParsingTests(unittest.TestCase):
    def test_graphql_parser_maps_license_spdx_id(self) -> None:
        node = {
            "id": "repo-1",
            "name": "repo",
            "owner": {"login": "owner"},
            "licenseInfo": {"spdxId": "MIT"},
        }
        self.assertEqual(_parse_graphql_repo(node)["license_spdx_id"], "MIT")

        no_license = _parse_graphql_repo(
            {"id": "repo-2", "name": "repo", "owner": {"login": "owner"}, "licenseInfo": None}
        )
        self.assertEqual(no_license["license_spdx_id"], "")

    def test_rest_parser_maps_license_spdx_id(self) -> None:
        item = {"full_name": "owner/repo", "license": {"spdx_id": "Apache-2.0"}}
        self.assertEqual(_parse_metrics_item(item)["license_spdx_id"], "Apache-2.0")

        no_license = _parse_metrics_item({"full_name": "owner/repo", "license": None})
        self.assertEqual(no_license["license_spdx_id"], "")

    def test_candidate_payload_carries_license_with_existing_fallback(self) -> None:
        payload = metrics._candidate_payload(
            {"full_name": "owner/repo", "license_spdx_id": "MIT"},
            existing=None,
            captured_at="now",
        )
        self.assertEqual(payload["license_spdx_id"], "MIT")

        # 本次抓取缺值时保留库中已有 license，不被空值冲掉
        retained = metrics._candidate_payload(
            {"full_name": "owner/repo"},
            existing={"license_spdx_id": "GPL-3.0"},
            captured_at="now",
        )
        self.assertEqual(retained["license_spdx_id"], "GPL-3.0")

        absent = metrics._candidate_payload(
            {"full_name": "owner/repo"}, existing=None, captured_at="now"
        )
        self.assertEqual(absent["license_spdx_id"], "")


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

    def test_success_stamps_response_time_and_failures_do_not(self) -> None:
        with patch.object(source_github, "_observed_now", return_value="2026-07-23T01:40:00+00:00"):
            with self._client(lambda _request: httpx.Response(200, json={"full_name": "owner/repo"})) as client:
                succeeded = fetch_github_repo_metrics("owner/repo", client=client, use_token=False)
            with self._client(lambda _request: httpx.Response(404)) as client:
                missing = fetch_github_repo_metrics("owner/repo", client=client, use_token=False)

        self.assertEqual(succeeded.observed_at, "2026-07-23T01:40:00+00:00")
        self.assertEqual(missing.observed_at, "")


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

    def test_rename_redirect_is_followed_once(self) -> None:
        payload = {
            "node_id": "repo-1",
            "full_name": "owner/new-name",
            "html_url": "https://github.com/owner/new-name",
            "stargazers_count": 42,
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url).endswith("/repos/owner/old-name"):
                return httpx.Response(
                    301,
                    headers={"location": "https://api.github.com/repos/owner/new-name"},
                )
            return httpx.Response(200, json=payload)

        with self._client(handler) as client:
            result = fetch_github_repo_metrics("owner/old-name", client=client, use_token=False)

        self.assertEqual(result.status, "succeeded")
        self.assertTrue(result.was_redirected)
        # full_name 保持请求名（旧名），权威新名在 metrics["full_name"]
        self.assertEqual(result.full_name, "owner/old-name")
        self.assertEqual(result.metrics["full_name"], "owner/new-name")
        self.assertEqual(result.metrics["repo_id"], "repo-1")

    def test_rename_redirect_then_404_is_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url).endswith("/repos/owner/old-name"):
                return httpx.Response(
                    301,
                    headers={"location": "https://api.github.com/repos/owner/gone"},
                )
            return httpx.Response(404)

        with self._client(handler) as client:
            result = fetch_github_repo_metrics("owner/old-name", client=client, use_token=False)

        self.assertEqual(result.status, "not_found")

    def test_numeric_id_redirect_is_followed(self) -> None:
        # 部分改名返回 ID 形态 Location：/repositories/{id}，负载仍带权威 full_name
        payload = {
            "node_id": "repo-9",
            "full_name": "new-owner/new-name",
            "html_url": "https://github.com/new-owner/new-name",
            "stargazers_count": 7,
        }

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url).endswith("/repos/old-owner/old-name"):
                return httpx.Response(
                    301,
                    headers={"location": "https://api.github.com/repositories/1281772914"},
                )
            return httpx.Response(200, json=payload)

        with self._client(handler) as client:
            result = fetch_github_repo_metrics("old-owner/old-name", client=client, use_token=False)

        self.assertEqual(result.status, "succeeded")
        self.assertTrue(result.was_redirected)
        self.assertEqual(result.full_name, "old-owner/old-name")
        self.assertEqual(result.metrics["full_name"], "new-owner/new-name")
        self.assertEqual(result.metrics["repo_id"], "repo-9")

    def test_numeric_id_redirect_then_404_is_not_found(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url).endswith("/repos/owner/old-name"):
                return httpx.Response(
                    301,
                    headers={"location": "https://api.github.com/repositories/999"},
                )
            return httpx.Response(404)

        with self._client(handler) as client:
            result = fetch_github_repo_metrics("owner/old-name", client=client, use_token=False)

        self.assertEqual(result.status, "not_found")

    def test_redirect_without_api_location_is_unknown(self) -> None:
        # 旧名被重用/跨域跳转等不可跟随重定向：fail-closed 记 unknown，绝不误判
        with self._client(
            lambda _request: httpx.Response(
                301, headers={"location": "https://github.com/owner/repo"}
            )
        ) as client:
            result = fetch_github_repo_metrics("owner/repo", client=client, use_token=False)

        self.assertEqual(result.status, "unknown")
        self.assertFalse(result.was_redirected)

    def test_second_redirect_hop_is_not_followed(self) -> None:
        # 最多跟随一跳：连续重定向视为异常形态，记 unknown 而非无限跟随
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                301,
                headers={"location": "https://api.github.com/repos/owner/elsewhere"},
            )

        with self._client(handler) as client:
            result = fetch_github_repo_metrics("owner/repo", client=client, use_token=False)

        self.assertEqual(result.status, "unknown")



class GitHubRepoMetricsBatchTests(unittest.TestCase):
    def test_graphql_chunks_stamp_their_own_response_time(self) -> None:
        # 一轮日刷要抓一到数小时：每批快照记该批响应到达时刻，而不是开轮时刻
        def handler(request: httpx.Request) -> httpx.Response:
            query = json.loads(request.content)["query"]
            owner, name = re.search(r'owner: "([^"]+)", name: "([^"]+)"', query).groups()
            node = {"id": f"id-{name}", "name": name, "owner": {"login": owner}, "stargazerCount": 7}
            return httpx.Response(200, json={"data": {"r0": node}})

        real_client = httpx.Client
        with (
            patch.object(source_github, "_get_token", return_value="token"),
            patch.object(
                source_github.httpx,
                "Client",
                lambda **_kwargs: real_client(transport=httpx.MockTransport(handler)),
            ),
            patch.object(
                source_github,
                "_observed_now",
                side_effect=["2026-07-23T00:17:05+00:00", "2026-07-23T01:52:40+00:00"],
            ),
        ):
            results = fetch_github_repo_metrics_batch(["owner/first", "owner/second"], batch_size=1)

        self.assertEqual([result.status for result in results], ["succeeded", "succeeded"])
        self.assertEqual(
            [result.observed_at for result in results],
            ["2026-07-23T00:17:05+00:00", "2026-07-23T01:52:40+00:00"],
        )


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

    def test_refresh_timestamps_follow_observation_with_round_start_fallback(self) -> None:
        repository = MagicMock()
        repository.list_github_project_metric_targets.return_value = [
            {"repo_id": "late", "full_name": "owner/late", "availability_status": "active"},
            {"repo_id": "legacy", "full_name": "owner/legacy", "availability_status": "active"},
        ]
        repository.upsert_github_repo_metric_observations.return_value = 2
        outcomes = [
            GitHubRepoMetricsResult(
                "owner/late",
                "succeeded",
                metrics={"repo_id": "late", "full_name": "owner/late", "stars": 10},
                http_status=200,
                observed_at="2026-07-23T01:52:40+00:00",
            ),
            GitHubRepoMetricsResult(
                "owner/legacy",
                "succeeded",
                metrics={"repo_id": "legacy", "full_name": "owner/legacy", "stars": 20},
                http_status=200,
            ),
        ]

        with (
            patch.object(metrics, "fetch_github_repo_metrics_batch", return_value=outcomes),
            patch.object(metrics, "_local_today", return_value=metrics.date(2026, 7, 23)),
            patch.object(metrics, "_utcnow", return_value="2026-07-23T00:17:00+00:00"),
        ):
            metrics.refresh_github_project_metric_snapshots(metric_date="2026-07-23", db=repository)

        call = repository.upsert_github_repo_metric_observations.call_args
        observations = {item["snapshot"]["full_name"]: item for item in call.args[0]}
        self.assertEqual(observations["owner/late"]["snapshot"]["captured_at"], "2026-07-23T01:52:40+00:00")
        self.assertEqual(observations["owner/late"]["candidate"]["last_snapshot_at"], "2026-07-23T01:52:40+00:00")
        self.assertEqual(observations["owner/legacy"]["snapshot"]["captured_at"], "2026-07-23T00:17:00+00:00")
        self.assertEqual(observations["owner/legacy"]["candidate"]["last_snapshot_at"], "2026-07-23T00:17:00+00:00")
        # 可用性检查时刻仍按轮记录
        self.assertEqual(call.kwargs["checked_at"], "2026-07-23T00:17:00+00:00")


    def test_refresh_flags_rename_via_renamed_from(self) -> None:
        # GraphQL 对改名仓库在旧名查询下返回新名数据：API 权威名与请求名不一致
        # → observation 携带 renamed_from，由仓储层归一/合并旧名行
        repository = MagicMock()
        repository.list_github_project_metric_targets.return_value = [
            {"repo_id": "node-1", "full_name": "owner/old-name", "availability_status": "active"},
        ]
        repository.upsert_github_repo_metric_observations.return_value = 1
        outcomes = [
            GitHubRepoMetricsResult(
                "owner/old-name",
                "succeeded",
                metrics={
                    "repo_id": "node-1",
                    "full_name": "owner/new-name",
                    "title": "owner/new-name",
                    "url": "https://github.com/owner/new-name",
                    "stars": 100,
                    "forks": 5,
                    "watchers": 6,
                    "open_issues": 0,
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

        observations = repository.upsert_github_repo_metric_observations.call_args.args[0]
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["renamed_from"], "owner/old-name")
        self.assertEqual(observations[0]["candidate"]["full_name"], "owner/new-name")
        self.assertEqual(observations[0]["snapshot"]["full_name"], "owner/new-name")
        self.assertEqual(result["renamed"], 1)
        self.assertEqual(result["fetched"], 1)

    def test_refresh_same_name_is_not_flagged_as_rename(self) -> None:
        repository = MagicMock()
        repository.list_github_project_metric_targets.return_value = [
            {"repo_id": "node-1", "full_name": "owner/repo", "availability_status": "active"},
        ]
        repository.upsert_github_repo_metric_observations.return_value = 1
        outcomes = [
            GitHubRepoMetricsResult(
                "owner/repo",
                "succeeded",
                metrics={"repo_id": "node-1", "full_name": "owner/repo", "stars": 10},
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

        observations = repository.upsert_github_repo_metric_observations.call_args.args[0]
        self.assertEqual(observations[0]["renamed_from"], "")
        self.assertEqual(result["renamed"], 0)


if __name__ == "__main__":
    unittest.main()
