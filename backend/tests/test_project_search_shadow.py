from __future__ import annotations

import time
from threading import Event

import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings
from backend.app.repositories.project_catalog import (
    ProjectLexicalCandidate,
    ProjectLexicalCandidateLanes,
)
from backend.app.services.project_search_shadow import ProjectSearchShadowManager


def test_search_strategy_defaults_to_legacy_and_rejects_unknown_values() -> None:
    config = Settings(
        _env_file=None,
        project_ai_search_strategy="legacy",
        project_search_shadow_epoch="default",
    )
    assert config.project_ai_search_strategy == "legacy"
    assert config.project_search_shadow_epoch == "default"
    with pytest.raises(ValidationError):
        Settings(_env_file=None, project_ai_search_strategy="unknown")


def test_search_shadow_is_fail_open_bounded_and_sanitized() -> None:
    manager = ProjectSearchShadowManager(
        workers=1,
        capacity=1,
        sample_rate=1.0,
        timeout_seconds=1.0,
        recent_case_limit=3,
    )
    lanes = ProjectLexicalCandidateLanes(
        strict=(ProjectLexicalCandidate("owner/strict", "strict", 2, 2),),
        relaxed=(ProjectLexicalCandidate("owner/relaxed", "relaxed", 1, 1),),
    )

    assert manager.submit(
        arguments={"query": "private query", "category": "secret"},
        legacy_repo_ids=["owner/strict"],
        lanes=lanes,
        semantic_repo_ids=[],
    )
    for _ in range(50):
        snapshot = manager.snapshot()
        if snapshot["recent_cases"]:
            break
        time.sleep(0.01)

    snapshot = manager.snapshot()
    case = snapshot["recent_cases"][0]
    assert case["outcome"] == "order_mismatch"
    assert case["strict_count"] == 1
    assert case["relaxed_count"] == 1
    serialized = str(snapshot)
    assert "private query" not in serialized
    assert "owner/strict" not in serialized
    assert "owner/relaxed" not in serialized
    assert manager.close(1)
    final = manager.snapshot()
    assert final["accounting"]["accepted"] == final["accounting"]["completed_terminal"] == 1
    assert final["accounting"]["terminal_failures"] == 1
    assert final["accounting"]["accounting_valid"] is True
    assert final["accounting"]["complete_coverage"] is False


def test_search_shadow_runs_candidate_lanes_inside_worker() -> None:
    manager = ProjectSearchShadowManager(
        workers=1,
        capacity=1,
        sample_rate=1.0,
        timeout_seconds=1.0,
        recent_case_limit=1,
    )
    called = []

    assert manager.submit(
        arguments={"query": "private query", "concept_count": 1},
        legacy_repo_ids=["owner/legacy"],
        lanes_call=lambda: called.append(True) or ProjectLexicalCandidateLanes(),
        semantic_repo_ids=[],
    )
    for _ in range(50):
        if manager.snapshot()["recent_cases"]:
            break
        time.sleep(0.01)

    assert called == [True]
    assert manager.snapshot()["recent_cases"][0]["outcome"] == "order_mismatch"
    assert manager.close(1)


def test_search_shadow_named_epoch_accounting_and_bounded_finalization() -> None:
    manager = ProjectSearchShadowManager(
        workers=1,
        capacity=1,
        sample_rate=1.0,
        timeout_seconds=1.0,
        recent_case_limit=1,
        epoch_name="search-v2",
    )
    release = Event()
    assert manager.submit(
        arguments={"query": "private query"},
        legacy_repo_ids=[],
        lanes_call=lambda: release.wait(1) or ProjectLexicalCandidateLanes(),
        semantic_repo_ids=[],
    )
    assert not manager.submit(
        arguments={"query": "another private query"},
        legacy_repo_ids=[],
        lanes=ProjectLexicalCandidateLanes(),
        semantic_repo_ids=[],
    )

    started = time.monotonic()
    assert manager.close(0.01) is False
    assert time.monotonic() - started < 0.2
    snapshot = manager.snapshot()
    assert snapshot["epoch"] == "search-v2"
    assert snapshot["lifecycle"] == "draining"
    assert snapshot["finalized_at"] is None
    assert snapshot["finalization_timed_out"] is True
    accounting = snapshot["accounting"]
    assert accounting["attempted"] == accounting["sampled_out"] + accounting["eligible"] == 2
    assert accounting["eligible"] == (
        accounting["accepted"]
        + accounting["skipped_unavailable"]
        + accounting["skipped_saturated"]
        + accounting["submit_errors"]
    ) == 2
    assert accounting["accepted"] == accounting["completed_terminal"] + accounting["in_flight"] == 1
    assert accounting["skipped_saturated"] == 1
    assert accounting["accounting_valid"] is True
    assert accounting["complete_coverage"] is False
    assert snapshot["sample_rate"] == 1
    assert "private query" not in str(snapshot)
    release.set()
    for _ in range(50):
        if manager.snapshot()["lifecycle"] == "finalized":
            break
        time.sleep(0.01)
    final = manager.snapshot()
    assert final["lifecycle"] == "finalized"
    assert final["accounting"]["completed_terminal"] == 1
    assert final["accounting"]["accounting_valid"] is True
    assert final["accounting"]["complete_coverage"] is False
