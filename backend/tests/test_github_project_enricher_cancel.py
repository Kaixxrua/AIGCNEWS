from __future__ import annotations

"""GitHubProjectEnricher 协作式终止：取消信号逐条生效、不写失败状态、退出后无残留。"""

import threading
import time
from unittest.mock import MagicMock

import pytest

from backend.app.domain.project_taxonomy import EnrichmentResult
from backend.app.repositories.project_write_repository import (
    GitHubProjectEnrichmentRepository,
)
from backend.app.services.ingestion import github_project_enricher
from backend.app.services.ingestion.github_project_enricher import (
    GitHubProjectEnricher,
    _EnrichmentCancelled,
    github_enrichment_batch_running,
    request_github_enrichment_cancel,
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


def _result() -> EnrichmentResult:
    return EnrichmentResult(
        category_slug="coding_tools",
        category_name="编程工具",
        subcategory_slug="ide_plugins",
        subcategory_name="IDE 插件",
        description_zh="一个用于测试的 AI 开源项目，覆盖协作式终止语义。",
        tags=["测试"],
        confidence=0.9,
        tags_en=["test"],
    )


def _repository(candidates: list[dict[str, object]]) -> MagicMock:
    repository = MagicMock(spec=GitHubProjectEnrichmentRepository)
    repository.runtime_provider_settings.get_runtime_provider_setting.return_value = {}
    repository.get_github_projects_needing_enrichment.return_value = candidates
    return repository


@pytest.fixture(autouse=True)
def _fast_pacing(monkeypatch) -> None:
    # 节流/退避在取消语义里只是等待窗口，测试中归零保持用例毫秒级
    monkeypatch.setattr(github_project_enricher, "_REQUEST_INTERVAL", 0)
    monkeypatch.setattr(github_project_enricher, "_RETRY_BASE_DELAY", 30.0)


def test_sequential_batch_stops_after_cancel_signal(monkeypatch) -> None:
    repository = _repository(_candidates(5))
    enricher = GitHubProjectEnricher(repository)
    completed: list[str] = []

    def fake_enrich_one(repo, *, cancel_event=None):
        completed.append(str(repo["repo_id"]))
        if len(completed) == 2:
            assert request_github_enrichment_cancel() is True
        return _result()

    monkeypatch.setattr(enricher, "_enrich_one", fake_enrich_one)

    result = enricher.enrich_batch(limit=5, concurrency=1)

    assert result["status"] == "cancelled"
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert result["cancelled"] == 3
    # 被终止的条目保持待处理：绝不能写入失败状态
    repository.mark_github_repo_enrichment_failed.assert_not_called()
    assert github_enrichment_batch_running() is False


def test_cancel_during_retry_backoff_wakes_promptly() -> None:
    repository = _repository(_candidates(1))
    enricher = GitHubProjectEnricher(repository)

    class _TimeoutLLM:
        def invoke(self, _messages):
            raise RuntimeError("request timeout")

    enricher._llm = _TimeoutLLM()

    def _cancel_soon() -> None:
        time.sleep(0.2)
        assert request_github_enrichment_cancel() is True

    threading.Thread(target=_cancel_soon, daemon=True).start()
    started = time.monotonic()
    result = enricher.enrich_batch(limit=1, concurrency=1)
    elapsed = time.monotonic() - started

    # 退避 30s 起步；取消后应立即醒来而不是睡满退避
    assert elapsed < 10
    assert result["status"] == "cancelled"
    assert result["succeeded"] == 0
    assert result["failed"] == 0
    assert result["cancelled"] == 1
    repository.mark_github_repo_enrichment_failed.assert_not_called()


def test_concurrent_batch_cancels_queued_items(monkeypatch) -> None:
    repository = _repository(_candidates(6))
    enricher = GitHubProjectEnricher(repository)

    def fake_enrich_one(repo, *, cancel_event=None):
        if cancel_event is not None and cancel_event.is_set():
            raise _EnrichmentCancelled("stop")
        # 首个进入的任务触发全局终止，其余排队任务应被短路
        request_github_enrichment_cancel()
        return _result()

    monkeypatch.setattr(enricher, "_enrich_one", fake_enrich_one)

    result = enricher.enrich_batch(limit=6, concurrency=3)

    assert result["status"] == "cancelled"
    assert result["succeeded"] >= 1
    assert result["cancelled"] >= 1
    assert result["succeeded"] + result["failed"] + result["cancelled"] == 6
    repository.mark_github_repo_enrichment_failed.assert_not_called()


def test_idle_cancel_is_noop_and_leaves_no_sticky_signal(monkeypatch) -> None:
    assert github_enrichment_batch_running() is False
    assert request_github_enrichment_cancel() is False

    # 空闲时的取消不得留下残留信号：下一批必须能正常跑完
    repository = _repository(_candidates(2))
    enricher = GitHubProjectEnricher(repository)
    monkeypatch.setattr(enricher, "_enrich_one", lambda repo, *, cancel_event=None: _result())

    result = enricher.enrich_batch(limit=2, concurrency=1)

    assert result["status"] == "success"
    assert result["succeeded"] == 2
    assert result["cancelled"] == 0
    assert github_enrichment_batch_running() is False


def test_running_flag_visible_during_batch(monkeypatch) -> None:
    repository = _repository(_candidates(1))
    enricher = GitHubProjectEnricher(repository)
    observed: list[bool] = []

    def fake_enrich_one(repo, *, cancel_event=None):
        observed.append(github_enrichment_batch_running())
        return _result()

    monkeypatch.setattr(enricher, "_enrich_one", fake_enrich_one)

    result = enricher.enrich_batch(limit=1, concurrency=1)

    assert result["status"] == "success"
    assert observed == [True]
    assert github_enrichment_batch_running() is False


def test_new_batch_does_not_revoke_older_batch_cancel_signal(monkeypatch) -> None:
    """每批次独立取消信号：新批次进入不得撤销旧批次已收到的取消请求。"""
    enricher_a = GitHubProjectEnricher(_repository(_candidates(3)))
    enricher_b = GitHubProjectEnricher(_repository(_candidates(2)))
    started = threading.Event()
    release = threading.Event()
    observed: list[bool] = []

    def slow_enrich_one(repo, *, cancel_event=None):
        started.set()
        if not release.wait(timeout=5):
            raise RuntimeError("test timed out waiting for release")
        # 旧批次恢复执行时必须仍持有已置位的取消信号
        observed.append(bool(cancel_event and cancel_event.is_set()))
        if cancel_event is not None and cancel_event.is_set():
            raise _EnrichmentCancelled("stop")
        return _result()

    monkeypatch.setattr(enricher_a, "_enrich_one", slow_enrich_one)
    monkeypatch.setattr(
        enricher_b, "_enrich_one", lambda repo, *, cancel_event=None: _result()
    )

    result_a: dict = {}
    thread = threading.Thread(
        target=lambda: result_a.update(enricher_a.enrich_batch(limit=3, concurrency=1)),
        daemon=True,
    )
    thread.start()
    assert started.wait(timeout=5)
    assert request_github_enrichment_cancel() is True

    # 旧批次取消信号已置位时，新批次以干净信号起步并正常跑完
    result_b = enricher_b.enrich_batch(limit=2, concurrency=1)
    assert result_b["status"] == "success"
    assert result_b["succeeded"] == 2

    release.set()
    thread.join(timeout=5)

    assert observed == [True]
    assert result_a["status"] == "cancelled"
    assert result_a["cancelled"] == 3
    repository_a_marks = enricher_a.db.mark_github_repo_enrichment_failed
    repository_a_marks.assert_not_called()
    assert github_enrichment_batch_running() is False
