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

    def test_rate_limit_is_told_apart_from_repository_level_403(self) -> None:
        cases = (
            ("quota exhausted", httpx.Response(403, headers={"x-ratelimit-remaining": "0"}), True),
            ("secondary limit", httpx.Response(403, headers={"retry-after": "60"}), True),
            (
                "limit message",
                httpx.Response(403, json={"message": "API rate limit exceeded for 1.2.3.4."}),
                True,
            ),
            ("too many requests", httpx.Response(429), True),
            (
                "access blocked",
                httpx.Response(
                    403,
                    headers={"x-ratelimit-remaining": "4999"},
                    json={"message": "Repository access blocked"},
                ),
                False,
            ),
        )
        for label, response, expected in cases:
            with self.subTest(label):
                with self._client(lambda _request, resp=response: resp) as client:
                    result = fetch_github_repo_metrics("owner/repo", client=client, use_token=False)
                self.assertEqual(result.status, "unknown")
                self.assertEqual(result.rate_limited, expected)


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



class TokenProbeTests(unittest.TestCase):
    def _probe(self, handler) -> bool:
        with (
            patch.object(source_github, "_get_token", return_value="token"),
            httpx.Client(transport=httpx.MockTransport(handler)) as client,
        ):
            return source_github._check_token_valid(client)

    def test_only_401_marks_the_token_invalid(self) -> None:
        # Search API 被限流或抖动说明不了 token 真伪；判无效会让整轮 REST 匿名执行
        for status_code, expected in ((200, True), (403, True), (429, True), (502, True), (401, False)):
            with self.subTest(status_code=status_code):
                self.assertEqual(
                    self._probe(lambda _request, code=status_code: httpx.Response(code)),
                    expected,
                )

    def test_probe_transport_failure_keeps_the_token(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("EOF occurred in violation of protocol", request=request)

        self.assertTrue(self._probe(handler))

    def test_missing_token_is_invalid_without_probing(self) -> None:
        probe = MagicMock()
        with patch.object(source_github, "_get_token", return_value=""):
            self.assertFalse(source_github._check_token_valid(probe))
        probe.get.assert_not_called()


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


_GRAPHQL_REPO = re.compile(r'(r\d+): repository\(owner: "([^"]+)", name: "([^"]+)"\)')


class GitHubRepoMetricsBatchResilienceTests(unittest.TestCase):
    """2026-09-29 日刷：一次 GraphQL 499 让整轮退成两万多次 REST，几乎全部 403/429。"""

    def setUp(self) -> None:
        self.graphql_posts = 0
        self.rest_gets: list[str] = []
        # 第 N 次 GraphQL POST（从 1 计）的覆盖响应；其余正常应答
        self.graphql_overrides: dict[int, httpx.Response | Exception] = {}
        # 按首个仓库名让某一批始终失败
        self.failing_chunk_heads: set[str] = set()
        # GraphQL 应答里节点为空的仓库（下架/改名）
        self.null_nodes: set[str] = set()
        self.rest_responses: dict[str, httpx.Response] = {}

    def _handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/graphql":
            self.graphql_posts += 1
            repos = _GRAPHQL_REPO.findall(json.loads(request.content)["query"])
            override = self.graphql_overrides.get(self.graphql_posts)
            if isinstance(override, Exception):
                raise override
            if override is not None:
                return override
            if f"{repos[0][1]}/{repos[0][2]}" in self.failing_chunk_heads:
                return httpx.Response(502)
            data = {
                alias: None
                if f"{owner}/{name}" in self.null_nodes
                else {"id": f"id-{name}", "name": name, "owner": {"login": owner}, "stargazerCount": 7}
                for alias, owner, name in repos
            }
            return httpx.Response(200, json={"data": data})
        if request.url.path.startswith("/search/"):
            return httpx.Response(200, json={"items": []})
        full_name = request.url.path.removeprefix("/repos/")
        self.rest_gets.append(full_name)
        return self.rest_responses.get(full_name) or httpx.Response(
            200, json={"full_name": full_name, "node_id": f"rest-{full_name}", "stargazers_count": 3}
        )

    def _fetch(self, names: list[str], **kwargs) -> tuple[list[GitHubRepoMetricsResult], MagicMock]:
        real_client = httpx.Client
        with (
            patch.object(source_github, "_get_token", return_value="token"),
            patch.object(
                source_github.httpx,
                "Client",
                lambda **_kwargs: real_client(transport=httpx.MockTransport(self._handler)),
            ),
            patch.object(source_github.time, "sleep") as sleep,
        ):
            results = fetch_github_repo_metrics_batch(names, **kwargs)
        return results, sleep

    def test_transient_graphql_failure_is_retried_instead_of_abandoning_the_round(self) -> None:
        request = httpx.Request("POST", "https://api.github.com/graphql")
        self.graphql_overrides = {
            1: httpx.Response(499),
            2: httpx.ReadError("SSL: UNEXPECTED_EOF_WHILE_READING", request=request),
        }

        results, sleep = self._fetch(["o/a", "o/b", "o/c"], batch_size=1)

        self.assertEqual([result.status for result in results], ["succeeded"] * 3)
        self.assertEqual(self.graphql_posts, 5)
        self.assertEqual(self.rest_gets, [])
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [5.0, 10.0])

    def test_one_bad_chunk_does_not_take_down_the_rest(self) -> None:
        self.failing_chunk_heads = {"o/a"}

        results, _sleep = self._fetch(["o/a", "o/b", "o/c"], batch_size=1)

        # 坏批重试耗尽后放弃，后续批次照常走 GraphQL；坏批仓库量小，退 REST 补抓
        self.assertEqual(self.graphql_posts, 3 + 2)
        self.assertEqual(self.rest_gets, ["o/a"])
        self.assertEqual([result.status for result in results], ["succeeded"] * 3)

    def test_consecutive_chunk_failures_stop_graphql(self) -> None:
        self.failing_chunk_heads = {"o/a", "o/b", "o/c"}

        self._fetch(["o/a", "o/b", "o/c", "o/d"], batch_size=1)

        # 连续三批重试后仍失败即停，o/d 不再发 GraphQL
        self.assertEqual(self.graphql_posts, 9)

    def test_large_unfetched_set_is_marked_unknown_instead_of_rest_fallback(self) -> None:
        self.graphql_overrides = {1: httpx.Response(429)}
        with patch.object(source_github, "_REST_FALLBACK_MAX_UNFETCHED", 2):
            results, _sleep = self._fetch(["o/a", "o/b", "o/c"], batch_size=1)

        self.assertEqual(self.rest_gets, [])
        self.assertEqual([result.status for result in results], ["unknown"] * 3)
        self.assertEqual(results[0].error, "GraphQL batch unavailable")

    def test_null_nodes_still_go_through_rest_to_detect_404_and_renames(self) -> None:
        # 首批正常应答但 o/b 节点为空；第二批限流中止，留下 o/c、o/d 未抓到
        self.null_nodes = {"o/b"}
        self.graphql_overrides = {2: httpx.Response(429)}
        self.rest_responses["o/b"] = httpx.Response(404)
        with patch.object(source_github, "_REST_FALLBACK_MAX_UNFETCHED", 1):
            results, _sleep = self._fetch(["o/a", "o/b", "o/c", "o/d"], batch_size=2)

        self.assertEqual(self.rest_gets, ["o/b"])
        self.assertEqual(
            [result.status for result in results],
            ["succeeded", "not_found", "unknown", "unknown"],
        )

    def test_small_unfetched_set_still_falls_back_to_rest(self) -> None:
        self.graphql_overrides = {1: httpx.Response(429)}

        results, _sleep = self._fetch(["o/a", "o/b"], batch_size=1)

        self.assertEqual(self.rest_gets, ["o/a", "o/b"])
        self.assertEqual([result.status for result in results], ["succeeded"] * 2)

    def test_rest_fallback_stops_at_the_first_rate_limit(self) -> None:
        self.null_nodes = {"o/a", "o/b", "o/c"}
        self.rest_responses["o/a"] = httpx.Response(403, headers={"x-ratelimit-remaining": "0"})

        results, _sleep = self._fetch(["o/a", "o/b", "o/c"], batch_size=3)

        self.assertEqual(self.rest_gets, ["o/a"])
        self.assertEqual([result.status for result in results], ["unknown"] * 3)
        self.assertTrue(all(result.rate_limited for result in results))
        self.assertEqual([result.http_status for result in results], [403, 403, 403])

    def test_repository_level_403_does_not_stop_the_fallback(self) -> None:
        self.null_nodes = {"o/a", "o/b"}
        self.rest_responses["o/a"] = httpx.Response(
            403, headers={"x-ratelimit-remaining": "4000"}, json={"message": "Repository access blocked"}
        )

        results, _sleep = self._fetch(["o/a", "o/b"], batch_size=2)

        self.assertEqual(self.rest_gets, ["o/a", "o/b"])
        self.assertEqual([result.status for result in results], ["unknown", "succeeded"])


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
        self.assertEqual(result["status"], "partial")
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

    def test_refresh_prunes_star_observations_without_failing_round(self) -> None:
        for prune_effect, expected in ((None, 1234), (RuntimeError("db down"), 0)):
            repository = MagicMock()
            repository.list_github_project_metric_targets.return_value = [
                {"repo_id": "live", "full_name": "owner/live", "availability_status": "active"},
            ]
            repository.upsert_github_repo_metric_observations.return_value = 1
            repository.prune_github_star_observations.return_value = 1234
            repository.prune_github_star_observations.side_effect = prune_effect
            outcomes = [
                GitHubRepoMetricsResult(
                    "owner/live",
                    "succeeded",
                    metrics={"repo_id": "live", "full_name": "owner/live", "stars": 10},
                    http_status=200,
                )
            ]
            with (
                patch.object(metrics, "fetch_github_repo_metrics_batch", return_value=outcomes),
                patch.object(metrics, "_local_today", return_value=metrics.date(2026, 7, 23)),
            ):
                result = metrics.refresh_github_project_metric_snapshots(metric_date="2026-07-23", db=repository)

            repository.prune_github_star_observations.assert_called_once_with()
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["snapshots"], 1)
            self.assertEqual(result["pruned_observations"], expected)


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


class GitHubMetricCheckpointTests(unittest.TestCase):
    def test_interrupted_refresh_saves_and_scores_before_fetching_next_batch(self):
        repository = MagicMock()
        names = [f"owner/repo{i}" for i in range(4)]
        written, scored = set(), set()
        repository.list_github_project_metric_targets.side_effect = lambda **kw: [
            {"repo_id": name, "full_name": name} for name in names if name not in scored
        ]

        def write(observations, **kwargs):
            written.update(row["candidate"]["full_name"] for row in observations)
            return len(observations)

        def compute(**kwargs):
            scored.update(kwargs.get("repo_ids", []))
            return {"status": "success"}

        def fetch(batch):
            if batch == names[2:]:
                self.assertEqual(written, set(names[:2]))
                self.assertEqual(scored, written)
                raise RuntimeError("process interrupted")
            return [GitHubRepoMetricsResult(name, "succeeded", metrics={"full_name": name, "stars": 600}) for name in batch]

        repository.upsert_github_repo_metric_observations.side_effect = write
        with (
            patch.object(metrics, "METRIC_CHECKPOINT_SIZE", 2),
            patch.object(metrics, "fetch_github_repo_metrics_batch", side_effect=fetch) as fetch_mock,
            patch.object(metrics, "compute_github_daily_metrics", side_effect=compute),
        ):
            with self.assertRaisesRegex(RuntimeError, "process interrupted"):
                metrics.refresh_and_compute_github_project_metrics(db=repository)
            # 模拟进程恢复：数据库中已完成的一批不再请求 GitHub。
            fetch_mock.side_effect = lambda batch: [
                GitHubRepoMetricsResult(name, "succeeded", metrics={"full_name": name, "stars": 600}) for name in batch
            ]
            result = metrics.refresh_and_compute_github_project_metrics(db=repository)
        self.assertEqual(result["refresh"]["targets"], 2)
        self.assertEqual(result["refresh"]["snapshots"], 2)
        self.assertEqual(fetch_mock.call_args.args[0], names[2:])
        self.assertEqual(scored, set(names))

    def test_unavailable_batch_stops_without_marking_remaining_repos_complete(self):
        repository = MagicMock()
        repository.list_github_project_metric_targets.return_value = [
            {"full_name": f"owner/repo{i}"} for i in range(4)
        ]
        with (
            patch.object(metrics, "METRIC_CHECKPOINT_SIZE", 2),
            patch.object(metrics, "fetch_github_repo_metrics_batch", return_value=[
                GitHubRepoMetricsResult("owner/repo0", "unknown"),
                GitHubRepoMetricsResult("owner/repo1", "unknown"),
            ]) as fetch,
        ):
            result = metrics.refresh_github_project_metric_snapshots(db=repository)
        fetch.assert_called_once()
        repository.upsert_github_repo_metric_observations.assert_not_called()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["processed"], 2)
        self.assertEqual(result["snapshots"], 0)


if __name__ == "__main__":
    unittest.main()
