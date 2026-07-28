from __future__ import annotations

import time
from threading import Event
from unittest.mock import MagicMock

from backend.app.repositories.project_catalog import (
    ProjectLexicalCandidate,
    ProjectLexicalCandidateLanes,
    ProjectLexicalConcept,
    ProjectLexicalRetrievalPlan,
)
from backend.app.services.project_catalog_shadow import (
    ProjectCatalogShadowManager,
    ShadowComparingProjectCatalogRepository,
    argument_fingerprint,
    compare_results,
)


def _manager(*, sample_rate: float = 1.0, workers: int = 1, capacity: int = 1):
    return ProjectCatalogShadowManager(
        workers=workers,
        capacity=capacity,
        sample_rate=sample_rate,
        timeout_seconds=1,
        recent_case_limit=5,
    )


def test_argument_fingerprint_is_deterministic_and_value_free() -> None:
    first = argument_fingerprint(
        "list_projects",
        {"q": "secret query", "user_id": 42, "candidate_repo_ids": ["a/b"]},
    )
    second = argument_fingerprint(
        "list_projects",
        {"q": "secret query", "user_id": 42, "candidate_repo_ids": ["a/b"]},
    )

    assert first == second
    assert "secret query" not in first
    assert "a/b" not in first
    assert "42" not in first


def test_argument_fingerprint_canonicalizes_typed_retrieval_plan() -> None:
    plan = ProjectLexicalRetrievalPlan(
        normalized_query="私密查询",
        strict_terms=("MCP",),
        concepts=(ProjectLexicalConcept("memory", ("代码库记忆",), ("codebase memory",)),),
    )

    first = argument_fingerprint("find_lexical_candidate_lanes", {"q": plan})
    second = argument_fingerprint("find_lexical_candidate_lanes", {"q": plan})

    assert first == second
    assert "私密查询" not in first
    assert "codebase memory" not in first


def test_comparator_distinguishes_order_set_pagination_and_fields() -> None:
    assert compare_results(
        "find_lexical_candidate_repo_ids", ["a", "b"], ["b", "a"]
    )[0] == "order_mismatch"
    assert compare_results(
        "find_lexical_candidate_repo_ids", ["a", "b"], ["a", "c"]
    )[0] == "set_mismatch"
    lanes = ProjectLexicalCandidateLanes(
        strict=(ProjectLexicalCandidate("a", "strict", 2, 4),),
        relaxed=(ProjectLexicalCandidate("b", "relaxed", 1, 1),),
    )
    assert compare_results("find_lexical_candidate_lanes", lanes, lanes)[0] == "match"
    changed_lanes = ProjectLexicalCandidateLanes(
        strict=lanes.strict,
        relaxed=(ProjectLexicalCandidate("c", "relaxed", 1, 1),),
    )
    assert compare_results("find_lexical_candidate_lanes", lanes, changed_lanes)[0] == "lane_mismatch"
    primary = {
        "items": [{"id": "github:a", "stars": 1}],
        "total": 1,
        "page": 1,
        "page_size": 24,
    }
    assert compare_results(
        "list_projects", primary, dict(primary, total=2)
    )[0] == "pagination_mismatch"
    shadow = dict(primary, items=[{"id": "github:a", "stars": 2}])
    assert compare_results("list_projects", primary, shadow)[0] == "field_mismatch"


def test_decorator_returns_exact_primary_object_and_preserves_error() -> None:
    active = MagicMock()
    shadow = MagicMock()
    manager = _manager(sample_rate=0)
    expected = {"items": [], "total": 0}
    active.list_projects.return_value = expected
    repository = ShadowComparingProjectCatalogRepository(active, shadow, manager)

    assert repository.list_projects(source="github") is expected
    shadow.list_projects.assert_not_called()

    error = RuntimeError("primary unavailable")
    active.list_projects.side_effect = error
    try:
        repository.list_projects(source="github")
    except RuntimeError as caught:
        assert caught is error
    else:
        raise AssertionError("primary error was not preserved")
    manager.close(0)


def test_shadow_error_is_fail_open_and_sanitized() -> None:
    active = MagicMock()
    shadow = MagicMock()
    manager = _manager()
    expected = {"items": [], "total": 0, "page": 1, "page_size": 24}
    active.list_projects.return_value = expected
    shadow.list_projects.side_effect = RuntimeError("postgresql://u:password@db")
    repository = ShadowComparingProjectCatalogRepository(active, shadow, manager)

    assert repository.list_projects(q="private query") is expected
    for _ in range(50):
        if manager.snapshot()["recent_cases"]:
            break
        time.sleep(0.01)
    snapshot = manager.snapshot()
    serialized = str(snapshot)
    assert snapshot["recent_cases"][0]["outcome"] == "shadow_error"
    assert snapshot["recent_cases"][0]["error_class"] == "RuntimeError"
    assert "password" not in serialized
    assert "private query" not in serialized
    assert manager.close(1)
    final = manager.snapshot()
    assert final["accounting"]["accepted"] == final["accounting"]["completed_terminal"] == 1
    assert final["accounting"]["terminal_failures"] == 1
    assert final["accounting"]["accounting_valid"] is True
    assert final["accounting"]["complete_coverage"] is False


def test_named_epoch_accounts_every_attempt_and_finalizes() -> None:
    manager = ProjectCatalogShadowManager(
        workers=1,
        capacity=1,
        sample_rate=0,
        timeout_seconds=1,
        recent_case_limit=1,
        epoch_name="catalog-v2",
    )

    assert not manager.submit(
        method="find_lexical_candidate_repo_ids",
        arguments={"q": "private"},
        primary=[],
        shadow_call=lambda: [],
    )
    assert manager.close(0)
    snapshot = manager.snapshot()

    assert snapshot["epoch"] == "catalog-v2"
    assert snapshot["lifecycle"] == "finalized"
    assert snapshot["finalized_at"]
    accounting = snapshot["accounting"]
    assert accounting["attempted"] == accounting["sampled_out"] + accounting["eligible"] == 1
    assert accounting["eligible"] == (
        accounting["accepted"]
        + accounting["skipped_unavailable"]
        + accounting["skipped_saturated"]
        + accounting["submit_errors"]
    ) == 0
    assert accounting["accepted"] == accounting["completed_terminal"] + accounting["in_flight"] == 0
    assert accounting["accounting_valid"] is True
    assert accounting["complete_coverage"] is False
    assert snapshot["sample_rate"] == 0
    assert "private" not in str(snapshot)


def test_close_is_bounded_and_reports_incomplete_drain() -> None:
    manager = _manager()
    release = Event()
    assert manager.submit(
        method="find_lexical_candidate_repo_ids",
        arguments={"q": "blocked"},
        primary=[],
        shadow_call=lambda: release.wait(1) or [],
    )

    started = time.monotonic()
    assert manager.close(0.01) is False
    assert time.monotonic() - started < 0.2
    snapshot = manager.snapshot()
    assert snapshot["lifecycle"] == "draining"
    assert snapshot["finalized_at"] is None
    assert snapshot["finalization_timed_out"] is True
    accounting = snapshot["accounting"]
    assert accounting["accepted"] == accounting["completed_terminal"] + accounting["in_flight"] == 1
    assert accounting["accounting_valid"] is True
    assert accounting["complete_coverage"] is False
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


def test_saturation_skips_without_waiting() -> None:
    manager = _manager()
    release = Event()
    assert manager.submit(
        method="find_lexical_candidate_repo_ids",
        arguments={"q": "first"},
        primary=[],
        shadow_call=lambda: release.wait(1) or [],
    )
    started = time.monotonic()
    accepted = manager.submit(
        method="find_lexical_candidate_repo_ids",
        arguments={"q": "second"},
        primary=[],
        shadow_call=lambda: [],
    )
    elapsed = time.monotonic() - started

    assert accepted is False
    assert elapsed < 0.1
    assert manager.snapshot()["counts"]["find_lexical_candidate_repo_ids"]["skipped_saturated"] == 1
    release.set()
    manager.close(1)
