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
    enrich_all_pending_github_projects,
    run_github_project_daily_pipeline,
)


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

        ingestion, enrichment, semantic = self._repositories()
        result = run_github_project_daily_pipeline(
            enrich_concurrency=5,
            ingestion=ingestion,
            enrichment=enrichment,
            semantic_sources=semantic,
        )

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
