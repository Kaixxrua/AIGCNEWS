from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings
from backend.app.repositories.project_catalog import (
    ProjectLexicalCandidate,
    ProjectLexicalCandidateLanes,
)
from backend.app.services.project_search_shadow import ProjectSearchShadowManager


def test_search_strategy_defaults_to_legacy_and_rejects_unknown_values() -> None:
    assert Settings(_env_file=None).project_ai_search_strategy == "legacy"
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
