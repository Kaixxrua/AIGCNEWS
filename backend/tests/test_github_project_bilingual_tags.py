from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.app.services.ingestion.github_project_enricher import GitHubProjectEnricher
from backend.app.services.ingestion.project_taxonomy import normalize_enrichment


def make_enricher() -> tuple[GitHubProjectEnricher, MagicMock]:
    repository = MagicMock()
    repository.get_runtime_provider_setting.return_value = {}
    with patch(
        "backend.app.services.ingestion.github_project_enricher._model_metadata",
        return_value={},
    ):
        return GitHubProjectEnricher(repository), repository


def test_normalize_enrichment_requires_paired_bilingual_tags() -> None:
    result = normalize_enrichment(
        {"tags_zh": ["代码助手"], "tags_en": ["Coding assistant"]},
        fallback_description="描述",
    )
    assert result.tags == ["代码助手"]
    assert result.tags_en == ["Coding assistant"]

    with pytest.raises(ValueError, match="一一对应"):
        normalize_enrichment(
            {"tags_zh": ["代码助手", "IDE"], "tags_en": ["Coding assistant"]},
            fallback_description="描述",
        )


def test_github_tag_backfill_dry_run_is_resumable_without_model_calls() -> None:
    enricher, repository = make_enricher()
    repository.list_github_projects_needing_bilingual_tags.return_value = [
        {"repo_id": "10", "full_name": "a/one"},
        {"repo_id": "20", "full_name": "b/two"},
    ]
    enricher._enrich_one = MagicMock()

    result = enricher.backfill_bilingual_tags(
        after_repo_id="5", limit=2, min_stars=500, dry_run=True,
    )

    assert result["status"] == "dry_run"
    assert result["processed"] == 2
    assert result["next_cursor"] == "20"
    assert result["has_more"] is True
    enricher._enrich_one.assert_not_called()
    repository.update_github_repo_system_tags.assert_not_called()


def test_github_tag_backfill_failure_preserves_successful_enrichment() -> None:
    enricher, repository = make_enricher()
    repository.list_github_projects_needing_bilingual_tags.return_value = [
        {"repo_id": "10", "full_name": "a/one"},
    ]
    enricher._enrich_one = MagicMock(side_effect=RuntimeError("model failed"))

    result = enricher.backfill_bilingual_tags(limit=1)

    assert result["status"] == "partial"
    repository.update_github_repo_system_tags.assert_not_called()
    repository.mark_github_repo_enrichment_failed.assert_not_called()
