from __future__ import annotations

"""每日流水线增长观察仓契约：全量爬取入参、富化清空循环、连续失败熔断。"""

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from backend.app.repositories.project_write_repository import (
    GitHubProjectEnrichmentRepository,
    GitHubProjectIngestionRepository,
    GitHubProjectSemanticSourceRepository,
)
from backend.app.services.ingestion import github_project_enricher
from backend.app.services.ingestion.github_project_enricher import (
    _CONSECUTIVE_FAILURE_BREAKER,
    GROWTH_OBSERVE_CHANNEL,
    GROWTH_OBSERVE_CRAWL_LIMIT,
    GROWTH_OBSERVE_CREATED_START,
    GROWTH_OBSERVE_MIN_STARS,
    GROWTH_OBSERVE_PUSHED_WINDOW_DAYS,
    GitHubProjectEnricher,
    _bootstrap_github_readmes,
    enrich_all_pending_github_projects,
    run_github_project_daily_pipeline,
)
from backend.app.services.ingestion.source_github import GitHubReadmeSnapshot


def _candidates(count: int) -> list[dict[str, object]]:
    return [
        {
            "repo_id": f"owner/repo-{index}",
            "full_name": f"owner/repo-{index}",
            "source_fingerprint": f"fp-{index}",
            "stars": 900,
        }
        for index in range(count)
    ]


def _repository(candidates: list[dict[str, object]]) -> MagicMock:
    repository = MagicMock(spec=GitHubProjectEnrichmentRepository)
    repository.runtime_provider_settings.get_runtime_provider_setting.return_value = {}
    repository.get_github_projects_needing_enrichment.return_value = candidates
    return repository


@pytest.fixture(autouse=True)
def _fast_pacing(monkeypatch) -> None:
    # 节流/退避只是等待窗口，测试中归零保持用例毫秒级
    monkeypatch.setattr(github_project_enricher, "_REQUEST_INTERVAL", 0)
    monkeypatch.setattr(github_project_enricher, "_RETRY_BASE_DELAY", 0)


class TestConsecutiveFailureBreaker:
    def test_serial_batch_breaks_and_keeps_remaining_pending(self, monkeypatch) -> None:
        repository = _repository(_candidates(_CONSECUTIVE_FAILURE_BREAKER + 10))
        enricher = GitHubProjectEnricher(db=repository)
        monkeypatch.setattr(
            enricher,
            "_enrich_and_store",
            lambda repo, *, cancel_event=None: False,
        )

        result = enricher.enrich_batch(limit=500, concurrency=1)

        assert result["breaker_tripped"] is True
        assert result["status"] == "cancelled"
        assert result["failed"] == _CONSECUTIVE_FAILURE_BREAKER
        # 熔断后未处理的条目记 cancelled（保持待处理），不得记失败
        assert result["cancelled"] == 10
        assert result["succeeded"] == 0

    def test_success_resets_consecutive_failure_counter(self, monkeypatch) -> None:
        repository = _repository(_candidates(_CONSECUTIVE_FAILURE_BREAKER + 5))
        enricher = GitHubProjectEnricher(db=repository)
        outcomes = [False] * (_CONSECUTIVE_FAILURE_BREAKER - 1) + [True] + [False] * 5
        iterator = iter(outcomes)
        monkeypatch.setattr(
            enricher,
            "_enrich_and_store",
            lambda repo, *, cancel_event=None: next(iterator),
        )

        result = enricher.enrich_batch(limit=500, concurrency=1)

        assert result["breaker_tripped"] is False
        assert result["status"] == "success"
        assert result["succeeded"] == 1
        assert result["failed"] == _CONSECUTIVE_FAILURE_BREAKER + 4

    def test_concurrent_batch_trips_breaker_without_mass_failure(self, monkeypatch) -> None:
        repository = _repository(_candidates(60))
        enricher = GitHubProjectEnricher(db=repository)

        def _always_fail(repo, *, cancel_event=None):
            # 尊重终止信号：模拟真实实现中未发起模型调用的条目
            if cancel_event is not None and cancel_event.is_set():
                return None
            return False

        monkeypatch.setattr(enricher, "_enrich_and_store", _always_fail)

        result = enricher.enrich_batch(limit=500, concurrency=4)

        assert result["breaker_tripped"] is True
        assert result["failed"] >= _CONSECUTIVE_FAILURE_BREAKER
        total = result["succeeded"] + result["failed"] + result["cancelled"]
        assert total == result["candidates"] == 60


class TestEnrichAllPending:
    def test_loops_until_queue_drained(self, monkeypatch) -> None:
        rounds = iter(
            [
                {"candidates": 500, "succeeded": 500, "failed": 0, "cancelled": 0},
                {"candidates": 120, "succeeded": 118, "failed": 2, "cancelled": 0},
                {"candidates": 2, "succeeded": 0, "failed": 2, "cancelled": 0},
            ]
        )
        calls: list[dict[str, object]] = []

        def _fake_batch(self, **kwargs):
            calls.append(kwargs)
            return next(rounds)

        monkeypatch.setattr(GitHubProjectEnricher, "enrich_batch", _fake_batch)
        repository = MagicMock(spec=GitHubProjectEnrichmentRepository)

        result = enrich_all_pending_github_projects(
            concurrency=5,
            min_stars=500,
            db=repository,
        )

        # 第三轮全部失败（无进展）即停：持续失败保持 failed 留待下轮，不空转
        assert result["status"] == "stalled"
        assert result["batches"] == 3
        assert result["succeeded"] == 618
        assert result["failed"] == 4
        assert all(call["retry_failed"] is True for call in calls)
        assert all(call["concurrency"] == 5 for call in calls)

    def test_stops_on_empty_queue(self, monkeypatch) -> None:
        monkeypatch.setattr(
            GitHubProjectEnricher,
            "enrich_batch",
            lambda self, **kwargs: {
                "candidates": 0,
                "succeeded": 0,
                "failed": 0,
                "cancelled": 0,
            },
        )
        repository = MagicMock(spec=GitHubProjectEnrichmentRepository)

        result = enrich_all_pending_github_projects(db=repository)

        assert result["status"] == "success"
        assert result["batches"] == 1

    def test_retry_disabled_passes_through_to_every_batch(self, monkeypatch) -> None:
        """两小时补跑链路：retry_failed=False 透传到每一批，failed 留待每日流水线。"""
        rounds = iter(
            [
                {"candidates": 500, "succeeded": 500, "failed": 0, "cancelled": 0},
                {"candidates": 0, "succeeded": 0, "failed": 0, "cancelled": 0},
            ]
        )
        calls: list[dict[str, object]] = []

        def _fake_batch(self, **kwargs):
            calls.append(kwargs)
            return next(rounds)

        monkeypatch.setattr(GitHubProjectEnricher, "enrich_batch", _fake_batch)
        repository = MagicMock(spec=GitHubProjectEnrichmentRepository)

        result = enrich_all_pending_github_projects(
            retry_failed=False,
            db=repository,
        )

        assert result["status"] == "success"
        assert result["batches"] == 2
        assert calls and all(call["retry_failed"] is False for call in calls)

    def test_stops_when_breaker_or_cancel_marks_cancelled(self, monkeypatch) -> None:
        monkeypatch.setattr(
            GitHubProjectEnricher,
            "enrich_batch",
            lambda self, **kwargs: {
                "candidates": 500,
                "succeeded": 12,
                "failed": 20,
                "cancelled": 468,
                "breaker_tripped": True,
            },
        )
        repository = MagicMock(spec=GitHubProjectEnrichmentRepository)

        result = enrich_all_pending_github_projects(db=repository)

        assert result["status"] == "cancelled"
        assert result["batches"] == 1
        assert result["cancelled"] == 468


class TestDailyPipelineGrowthObserve:
    def _repositories(self) -> tuple[MagicMock, MagicMock, MagicMock]:
        ingestion = MagicMock(spec=GitHubProjectIngestionRepository)
        enrichment = MagicMock(spec=GitHubProjectEnrichmentRepository)
        semantic = MagicMock(spec=GitHubProjectSemanticSourceRepository)
        return ingestion, enrichment, semantic

    def test_pipeline_runs_full_growth_crawl_and_unbounded_enrich(self, monkeypatch) -> None:
        calls: dict[str, dict[str, object]] = {}

        def _refresh(**kwargs):
            calls["refresh"] = kwargs
            return {"repos": 3}

        def _crawl(**kwargs):
            calls["crawl"] = kwargs
            return {"upserted": 42, "new_candidates": 7}

        def _metrics(**kwargs):
            calls["metrics"] = kwargs
            return {"refresh": {}, "metrics": {}}

        def _enrich_all(**kwargs):
            calls["enrich"] = kwargs
            return {"status": "success", "succeeded": 9}

        monkeypatch.setattr(github_project_enricher, "refresh_github_hot_candidates", _refresh)
        monkeypatch.setattr(github_project_enricher, "crawl_github_search", _crawl)
        monkeypatch.setattr(
            github_project_enricher,
            "refresh_and_compute_github_project_metrics",
            _metrics,
        )
        monkeypatch.setattr(
            github_project_enricher,
            "enrich_all_pending_github_projects",
            _enrich_all,
        )
        monkeypatch.setattr(
            github_project_enricher,
            "current_github_metric_date",
            lambda: "2026-08-08",
        )

        from backend.app.services.ingestion import github_project_logos
        logo_repository = object()
        def collect_logos(repository, **kwargs):
            assert repository is logo_repository
            assert "metrics" in calls
            calls["logos"] = kwargs
            return {"selected": 1, "found": 1}
        monkeypatch.setattr(github_project_logos, "refresh_project_logos", collect_logos)
        ingestion, enrichment, semantic = self._repositories()
        result = run_github_project_daily_pipeline(
            logo_repository=logo_repository,
            enrich_concurrency=5,
            ingestion=ingestion,
            enrichment=enrichment,
            semantic_sources=semantic,
        )

        assert result["logos"] == {"selected": 1, "found": 1}
        assert calls["logos"]["limit"] == 0

        # 旧 7 查询 Search 发现在流水线内关闭，由增长口径全量爬取接管
        assert calls["refresh"]["include_search"] is False
        crawl = calls["crawl"]
        assert crawl["min_stars"] == GROWTH_OBSERVE_MIN_STARS == 300
        assert crawl["max_stars"] == 0
        assert crawl["limit"] == GROWTH_OBSERVE_CRAWL_LIMIT
        assert crawl["created_start"] == GROWTH_OBSERVE_CREATED_START == date(2024, 6, 30)
        assert crawl["created_end"] == date.today()
        expected_pushed = (date.today() - timedelta(days=GROWTH_OBSERVE_PUSHED_WINDOW_DAYS)).isoformat()
        assert crawl["pushed_after"] == expected_pushed
        assert crawl["channel"] == GROWTH_OBSERVE_CHANNEL
        assert crawl["ingestion"] is ingestion

        # 富化不再限 50 个：走清空队列入口，并发以参数为准
        assert calls["enrich"]["concurrency"] == 5
        assert result["growth_observe"] == {"upserted": 42, "new_candidates": 7}
        assert result["enrichment"] == {"status": "success", "succeeded": 9}
        assert result["growth_observe_min_stars"] == 300

    def test_dry_run_skips_crawl_and_enriches_nothing(self, monkeypatch) -> None:
        def _forbidden(**kwargs):  # pragma: no cover - 命中即失败
            raise AssertionError("dry_run 不得触发写库侧抓取")

        dry_calls: dict[str, object] = {}

        def _dry_enrich(**kwargs):
            dry_calls.update(kwargs)
            return {"status": "dry_run", "candidates": 3}

        monkeypatch.setattr(github_project_enricher, "refresh_github_hot_candidates", _forbidden)
        monkeypatch.setattr(github_project_enricher, "crawl_github_search", _forbidden)
        monkeypatch.setattr(github_project_enricher, "enrich_github_projects", _dry_enrich)

        ingestion, enrichment, semantic = self._repositories()
        result = run_github_project_daily_pipeline(
            dry_run=True,
            ingestion=ingestion,
            enrichment=enrichment,
            semantic_sources=semantic,
        )

        assert result["status"] == "dry_run"
        assert result["growth_observe"] is None
        assert dry_calls["dry_run"] is True


class TestReadmeBootstrap:
    """README 预补水：description 为空的候选在富化前先落 README 快照。"""

    def _semantic(self, rows: list[dict[str, object]]) -> MagicMock:
        semantic = MagicMock(spec=GitHubProjectSemanticSourceRepository)
        semantic.list_github_projects_for_readme_bootstrap.side_effect = [rows, []]
        return semantic

    def _bootstrap_rows(self) -> list[dict[str, object]]:
        return [
            {
                "repo_id": "Alain00/blobatar",
                "full_name": "Alain00/blobatar",
                "pushed_at": "2026-08-01T00:00:00+00:00",
                "readme_text": "",
                "readme_sha256": "",
                "readme_etag": "",
            },
            {
                "repo_id": "amadeusprotocol/node",
                "full_name": "amadeusprotocol/node",
                "pushed_at": "2026-07-20T00:00:00+00:00",
                "readme_text": "",
                "readme_sha256": "",
                "readme_etag": "",
            },
            {
                "repo_id": "acme/rate-limited",
                "full_name": "acme/rate-limited",
                "pushed_at": "2026-07-20T00:00:00+00:00",
                "readme_text": "old kept text",
                "readme_sha256": "old-hash",
                "readme_etag": "old-etag",
            },
        ]

    def test_bootstrap_upserts_snapshots_without_touching_vectors(self, monkeypatch) -> None:
        snapshots = iter(
            [
                GitHubReadmeSnapshot(
                    status="succeeded",
                    text="Blobatar creates avatars",
                    etag="e1",
                    sha256="h1",
                ),
                GitHubReadmeSnapshot(status="not_found"),
                GitHubReadmeSnapshot(
                    status="rate_limited",
                    error="GitHub API returned 403",
                ),
            ]
        )
        monkeypatch.setattr(
            github_project_enricher,
            "fetch_github_readme_snapshot",
            lambda full_name, client, *, etag="", max_chars=0, use_token=True: next(snapshots),
        )
        semantic = self._semantic(self._bootstrap_rows())

        result = _bootstrap_github_readmes(semantic_sources=semantic, min_stars=500)

        assert result["status"] == "success"
        assert result["selected"] == 3
        assert result["succeeded"] == 1
        assert result["not_found"] == 1
        assert result["rate_limited"] == 1
        # selector 按 keyset 传 min_stars 游标；只写 semantic source 快照
        selector_kwargs = semantic.list_github_projects_for_readme_bootstrap.call_args_list[0].kwargs
        assert selector_kwargs["min_stars"] == 500
        upserts = [call.args[0] for call in semantic.upsert_github_project_readme_snapshot.call_args_list]
        assert upserts[0]["repo_id"] == "Alain00/blobatar"
        assert upserts[0]["readme_status"] == "succeeded"
        assert upserts[0]["readme_text"] == "Blobatar creates avatars"
        assert upserts[0]["readme_repo_pushed_at"] == "2026-08-01T00:00:00+00:00"
        # 404：清空残留 README，不再算可富化输入
        assert upserts[1]["readme_status"] == "not_found"
        assert upserts[1]["readme_text"] == ""
        assert upserts[1]["readme_sha256"] == ""
        # 限流：保留旧文本/hash，不得把已有内容抹掉
        assert upserts[2]["readme_status"] == "rate_limited"
        assert upserts[2]["readme_text"] == "old kept text"
        assert upserts[2]["readme_sha256"] == "old-hash"

    def test_not_modified_normalizes_to_succeeded_and_keeps_fetch_time(self, monkeypatch) -> None:
        rows = [
            {
                "repo_id": "acme/cached",
                "full_name": "acme/cached",
                "pushed_at": "2026-08-01T00:00:00+00:00",
                "readme_text": "cached README body",
                "readme_sha256": "cached-hash",
                "readme_etag": "cached-etag",
                "readme_fetched_at": "2026-08-10T00:00:00+00:00",
            }
        ]
        monkeypatch.setattr(
            github_project_enricher,
            "fetch_github_readme_snapshot",
            lambda *a, **k: GitHubReadmeSnapshot(status="not_modified", etag="new-etag"),
        )
        semantic = self._semantic(rows)

        result = _bootstrap_github_readmes(semantic_sources=semantic, min_stars=500)

        assert result["succeeded"] == 1
        upsert = semantic.upsert_github_project_readme_snapshot.call_args.args[0]
        # 304 语义：已有非空文本规范为 succeeded，快照 fetched_at 不刷新
        assert upsert["readme_status"] == "succeeded"
        assert upsert["readme_text"] == "cached README body"
        assert upsert["readme_sha256"] == "cached-hash"
        assert upsert["readme_fetched_at"] == "2026-08-10T00:00:00+00:00"

    def test_bootstrap_fetch_failure_does_not_raise_and_reports_partial(self, monkeypatch) -> None:
        def _explode(*args, **kwargs):
            raise RuntimeError("network exploded")

        monkeypatch.setattr(
            github_project_enricher,
            "fetch_github_readme_snapshot",
            _explode,
        )
        semantic = MagicMock(spec=GitHubProjectSemanticSourceRepository)
        semantic.list_github_projects_for_readme_bootstrap.side_effect = [
            [{"repo_id": "a/b", "full_name": "a/b", "pushed_at": "2026-08-01"}],
        ]

        result = _bootstrap_github_readmes(semantic_sources=semantic, min_stars=500)

        # bootstrap 异常不得阻断富化主流程；已圈选但未完成的部分记 partial
        assert result["status"] == "partial"
        assert result["selected"] == 1
        assert result["succeeded"] == 0
        assert "network exploded" in result["error"]

    def test_bootstrap_selector_failure_reports_failed(self, monkeypatch) -> None:
        semantic = MagicMock(spec=GitHubProjectSemanticSourceRepository)
        semantic.list_github_projects_for_readme_bootstrap.side_effect = RuntimeError(
            "db down"
        )

        result = _bootstrap_github_readmes(semantic_sources=semantic, min_stars=500)

        # 连圈选都失败时不得影响后续富化，状态如实记 failed
        assert result["status"] == "failed"
        assert result["selected"] == 0
        assert "db down" in result["error"]

    def test_pipeline_runs_bootstrap_before_enrichment(self, monkeypatch) -> None:
        order: list[str] = []

        def _bootstrap(**kwargs):
            order.append("bootstrap")
            return {"status": "success", "selected": 0}

        def _enrich_all(**kwargs):
            order.append("enrich")
            return {"status": "success"}

        monkeypatch.setattr(github_project_enricher, "refresh_github_hot_candidates", lambda **k: {})
        monkeypatch.setattr(github_project_enricher, "crawl_github_search", lambda **k: {})
        monkeypatch.setattr(github_project_enricher, "refresh_and_compute_github_project_metrics", lambda **k: {})
        monkeypatch.setattr(github_project_enricher, "_bootstrap_github_readmes", _bootstrap)
        monkeypatch.setattr(github_project_enricher, "enrich_all_pending_github_projects", _enrich_all)
        monkeypatch.setattr(github_project_enricher, "current_github_metric_date", lambda: "2026-08-21")

        ingestion = MagicMock(spec=GitHubProjectIngestionRepository)
        enrichment = MagicMock(spec=GitHubProjectEnrichmentRepository)
        semantic = MagicMock(spec=GitHubProjectSemanticSourceRepository)
        result = run_github_project_daily_pipeline(
            ingestion=ingestion,
            enrichment=enrichment,
            semantic_sources=semantic,
        )

        # 先补 README 再圈选富化队列；结果透出到流水线返回体
        assert order == ["bootstrap", "enrich"]
        assert result["readme_bootstrap"] == {"status": "success", "selected": 0}

    def test_dry_run_skips_readme_bootstrap(self, monkeypatch) -> None:
        def _forbidden(**kwargs):  # pragma: no cover - 命中即失败
            raise AssertionError("dry_run 不得抓取 README")

        monkeypatch.setattr(github_project_enricher, "_bootstrap_github_readmes", _forbidden)
        monkeypatch.setattr(
            github_project_enricher,
            "enrich_github_projects",
            lambda **k: {"status": "dry_run", "candidates": 0},
        )

        ingestion = MagicMock(spec=GitHubProjectIngestionRepository)
        enrichment = MagicMock(spec=GitHubProjectEnrichmentRepository)
        semantic = MagicMock(spec=GitHubProjectSemanticSourceRepository)
        result = run_github_project_daily_pipeline(
            dry_run=True,
            ingestion=ingestion,
            enrichment=enrichment,
            semantic_sources=semantic,
        )

        assert result["readme_bootstrap"] == {"status": "disabled"}
        semantic.list_github_projects_for_readme_bootstrap.assert_not_called()
