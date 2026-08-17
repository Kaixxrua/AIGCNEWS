from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.app.domain.project_taxonomy import (
    PROMPT_VERSION,
    EnrichmentResult,
    normalize_enrichment,
    raw_description_needs_english,
)
from backend.app.services.ingestion.github_project_enricher import GitHubProjectEnricher


def make_enricher() -> tuple[GitHubProjectEnricher, MagicMock]:
    repository = MagicMock()
    repository.get_runtime_provider_setting.return_value = {}
    with patch(
        "backend.app.services.ingestion.github_project_enricher._model_metadata",
        return_value={},
    ):
        return GitHubProjectEnricher(repository), repository


def _v6_result(
    description_en: str = "A useful English description of the project.",
) -> EnrichmentResult:
    return EnrichmentResult(
        category_slug="coding_tools",
        category_name="AI 编程工具",
        subcategory_slug="ide_plugins",
        subcategory_name="IDE 插件",
        description_zh="一句中文描述。",
        tags=["代码助手"],
        confidence=0.9,
        description_en=description_en,
        tags_en=["Coding assistant"],
    )


def test_normalize_enrichment_requires_english_description() -> None:
    with pytest.raises(ValueError, match="必须返回英文描述"):
        normalize_enrichment(
            {"tags_zh": ["代码助手"], "tags_en": ["Coding assistant"]},
            fallback_description="描述",
        )


def test_normalize_enrichment_rejects_chinese_in_english_description() -> None:
    with pytest.raises(ValueError, match="英文描述不得包含中文"):
        normalize_enrichment(
            {
                "description_en": "An English description with 中文 mixed in.",
                "tags_zh": ["代码助手"],
                "tags_en": ["Coding assistant"],
            },
            fallback_description="描述",
        )


def test_normalize_enrichment_accepts_v6_payload() -> None:
    result = normalize_enrichment(
        {
            "category_slug": "coding_tools",
            "subcategory_slug": "ide_plugins",
            "description_zh": "一句中文描述。",
            "description_en": "A natural one-sentence English description of the project.",
            "tags_zh": ["IDE 插件"],
            "tags_en": ["IDE plugin"],
            "confidence": 0.9,
        },
        fallback_description="描述",
    )
    assert result.category_slug == "coding_tools"
    assert result.description_en == "A natural one-sentence English description of the project."
    assert result.tags_en == ["IDE plugin"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, True),
        ("", True),
        ("   ", True),
        ("Ethereum smart contract fuzzer", True),  # 30 chars < 50
        ("A " + "x" * 60, False),  # adequate English
        (
            "微信重复文件清理工具。采用智能哈希算法极速识别重复文件，"
            "支持可视化预览与安全删除，移至回收站，微信聊天文件瘦身利器。",
            True,  # CJK majority
        ),
        (
            "A Gradle plugin for 微信小程序 tooling with incremental builds and caching support",
            False,  # English sentence with a Chinese product name (minority CJK)
        ),
    ],
)
def test_raw_description_needs_english(raw: object, expected: bool) -> None:
    assert raw_description_needs_english(raw) is expected


def test_english_backfill_dry_run_makes_no_model_calls() -> None:
    enricher, repository = make_enricher()
    repository.list_github_projects_needing_english_description.return_value = [
        {"repo_id": "10", "full_name": "a/one"},
        {"repo_id": "20", "full_name": "b/two"},
    ]
    enricher._enrich_one = MagicMock()

    result = enricher.backfill_english_descriptions(after_repo_id="5", limit=2, dry_run=True)

    assert result["status"] == "dry_run"
    assert result["processed"] == 2
    assert result["next_cursor"] == "20"
    assert result["has_more"] is True
    enricher._enrich_one.assert_not_called()
    repository.update_github_repo_description_en.assert_not_called()


def test_english_backfill_updates_only_english_description() -> None:
    enricher, repository = make_enricher()
    repository.list_github_projects_needing_english_description.return_value = [
        {"repo_id": "10", "full_name": "a/one"},
    ]
    enricher._enrich_one = MagicMock(return_value=_v6_result())

    result = enricher.backfill_english_descriptions(limit=1, concurrency=1)

    assert result["status"] == "success"
    assert result["succeeded"] == 1
    repository.update_github_repo_description_en.assert_called_once_with(
        repo_id="10",
        description_en="A useful English description of the project.",
        prompt_version=PROMPT_VERSION,
    )
    repository.upsert_github_repo_enrichment.assert_not_called()
    repository.mark_github_repo_enrichment_failed.assert_not_called()


def test_english_backfill_failure_keeps_row_pending() -> None:
    enricher, repository = make_enricher()
    repository.list_github_projects_needing_english_description.return_value = [
        {"repo_id": "10", "full_name": "a/one"},
    ]
    enricher._enrich_one = MagicMock(side_effect=RuntimeError("model failed"))

    result = enricher.backfill_english_descriptions(limit=1, concurrency=1)

    assert result["status"] == "partial"
    assert result["failed"] == 1
    assert result["failures"] == [{"repo_id": "10", "error": "model failed"}]
    repository.update_github_repo_description_en.assert_not_called()


def test_english_backfill_runs_concurrently() -> None:
    enricher, repository = make_enricher()
    repository.list_github_projects_needing_english_description.return_value = [
        {"repo_id": str(index), "full_name": f"owner/repo-{index}"}
        for index in range(6)
    ]
    enricher._enrich_one = MagicMock(side_effect=lambda row: _v6_result())

    result = enricher.backfill_english_descriptions(limit=6, concurrency=3)

    assert result["status"] == "success"
    assert result["succeeded"] == 6
    assert repository.update_github_repo_description_en.call_count == 6
