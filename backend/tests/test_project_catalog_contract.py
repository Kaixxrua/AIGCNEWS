from __future__ import annotations

import asyncio
import inspect
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.app.api import routes_github_projects
from backend.app.repositories.project_catalog import ProjectCatalogRepository
from backend.app.services import project_discovery

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "project_catalog_cases.json"
PUBLIC_PROJECT_FIELDS = {
    "id",
    "full_name",
    "url",
    "description",
    "description_zh",
    "description_en",
    "category_slug",
    "category_name",
    "category_name_zh",
    "category_name_en",
    "subcategory_slug",
    "subcategory_name",
    "subcategory_name_zh",
    "subcategory_name_en",
    "tags",
    "tags_zh",
    "tags_en",
    "tags_origin",
    "topics",
    "language",
    "license",
    "stars",
    "forks",
    "pushed_at",
    "daily_star_growth",
    "daily_growth_available",
    "hot_score",
    "growth_suspicion_score",
    "is_recommended",
    "result_origin",
}


def load_catalog_cases() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_taxonomy_exposes_complete_bilingual_labels_with_chinese_legacy_aliases() -> None:
    from backend.app.domain.project_taxonomy import (
        PROJECT_TAXONOMY,
        WEBSITE_TAXONOMY,
    )

    for taxonomy in (PROJECT_TAXONOMY, WEBSITE_TAXONOMY):
        for category in taxonomy:
            assert category["name"] == category["name_zh"]
            assert category["name_en"]
            for child in category["children"]:
                assert child["name"] == child["name_zh"]
                assert child["name_en"]


def test_project_api_taxonomy_keeps_legacy_name_chinese() -> None:
    items = routes_github_projects._taxonomy_items()
    assert items
    assert all(item["name"] == item["name_zh"] and item["name_en"] for item in items)
    assert all(
        child["name"] == child["name_zh"] and child["name_en"]
        for item in items for child in item["children"]
    )


class ScriptedCatalogRepository:
    def __init__(self, fixture: dict[str, Any], results: list[dict[str, Any]]) -> None:
        self.fixture = fixture
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []

    def list_projects(
        self,
        *,
        source: str = "all",
        scope: str = "all",
        category: str = "",
        subcategory: str = "",
        q: str = "",
        language: str = "",
        tag: str = "",
        page: int = 1,
        page_size: int = 24,
        sort: str = "stars",
        min_stars: int = 500,
        enriched_only: bool = True,
        user_id: int | None = None,
        favorites_only: bool = False,
        candidate_repo_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "source": source,
                "scope": scope,
                "category": category,
                "subcategory": subcategory,
                "q": q,
                "language": language,
                "tag": tag,
                "page": page,
                "page_size": page_size,
                "sort": sort,
                "min_stars": min_stars,
                "enriched_only": enriched_only,
                "user_id": user_id,
                "favorites_only": favorites_only,
                "candidate_repo_ids": candidate_repo_ids,
            }
        )
        scripted = self.results.pop(0)
        items = [deepcopy(self.fixture["projects"][key]) for key in scripted["project_keys"]]
        return {
            "items": items,
            "total": scripted["total"],
            "page": page,
            "page_size": page_size,
        }

    def count_github_catalog_candidates(self, *, min_stars: int = 500) -> int:
        return 0

    def get_project_categories(
        self,
        *,
        source: str = "all",
        min_stars: int = 500,
        enriched_only: bool = True,
        user_id: int | None = None,
        favorites_only: bool = False,
    ) -> dict[str, Any]:
        return deepcopy(self.fixture["categories"])


def _without_annotations(function: Any) -> inspect.Signature:
    signature = inspect.signature(function)
    parameters = [parameter.replace(annotation=inspect.Parameter.empty) for parameter in signature.parameters.values()]
    return signature.replace(parameters=parameters, return_annotation=inspect.Signature.empty)


def test_catalog_read_signatures_are_frozen() -> None:
    list_signature = _without_annotations(ScriptedCatalogRepository.list_projects)
    categories_signature = _without_annotations(ScriptedCatalogRepository.get_project_categories)
    count_signature = _without_annotations(ScriptedCatalogRepository.count_github_catalog_candidates)

    assert _without_annotations(ProjectCatalogRepository.count_github_catalog_candidates) == count_signature
    assert _without_annotations(ProjectCatalogRepository.list_projects) == list_signature
    assert _without_annotations(ProjectCatalogRepository.get_project_categories) == categories_signature


@pytest.mark.parametrize("case_index", [0, 1])
def test_discovery_golden_cases(case_index: int) -> None:
    fixture = load_catalog_cases()
    case = fixture["discovery_cases"][case_index]
    repository = ScriptedCatalogRepository(fixture, case["repository_results"])
    fallback = MagicMock()

    with patch.object(project_discovery.settings, "project_semantic_search_enabled", False):
        result = asyncio.run(
            project_discovery.search_projects(
                **case["request"],
                repository_factory=lambda: repository,
                fallback_search=fallback,
            )
        )

    assert {key: repository.calls[0][key] for key in case["expected_call"]} == case["expected_call"]
    assert [item["id"] for item in result["items"]] == case["expected"]["ids"]
    for key, value in case["expected"].items():
        if key != "ids":
            assert result[key] == value
    assert all(set(item) == PUBLIC_PROJECT_FIELDS for item in result["items"])
    fallback.assert_not_called()


def test_semantic_candidate_hydration_preserves_catalog_order_and_contract() -> None:
    fixture = load_catalog_cases()
    case = fixture["semantic_case"]
    repository = ScriptedCatalogRepository(fixture, case["repository_results"])
    semantic = MagicMock()
    semantic.search_repo_ids.return_value = [
        SimpleNamespace(repo_id=repo_id, score=1.0 - index / 10)
        for index, repo_id in enumerate(case["candidate_repo_ids"])
    ]
    fallback = MagicMock()

    with patch.object(project_discovery.settings, "project_semantic_search_enabled", True):
        result = asyncio.run(
            project_discovery.search_projects(
                **case["request"],
                repository_factory=lambda: repository,
                semantic_search_factory=lambda: semantic,
                fallback_search=fallback,
            )
        )

    assert [item["id"] for item in result["items"]] == case["expected_ids"]
    assert repository.calls[0]["q"] == "local knowledge"
    assert repository.calls[0]["sort"] == "relevance"
    assert repository.calls[1]["q"] == ""
    assert repository.calls[1]["sort"] == "relevance"
    assert repository.calls[1]["candidate_repo_ids"] == case["candidate_repo_ids"]
    assert result["sort"] == "relevance"
    assert result["result_origin"] == "aigc_news_local"
    assert result["fallback_used"] is False
    fallback.assert_not_called()


@pytest.mark.parametrize(
    ("search_request", "skip_reason"),
    [
        ({"query": "agent", "mode": "ai", "page": 2}, "fallback_is_first_page_only"),
        (
            {"query": "agent", "mode": "ai", "category": "agents_automation"},
            "taxonomy_filter_requires_local_classification",
        ),
        ({"query": "agent", "mode": "ai", "sort": "name"}, "sort_not_equivalent_on_github_search"),
    ],
)
def test_lossy_fallback_paths_are_frozen(search_request: dict[str, Any], skip_reason: str) -> None:
    fixture = load_catalog_cases()
    repository = ScriptedCatalogRepository(fixture, [{"project_keys": [], "total": 0}])
    fallback = MagicMock()

    with patch.object(project_discovery.settings, "project_semantic_search_enabled", False):
        result = asyncio.run(
            project_discovery.search_projects(
                **search_request,
                repository_factory=lambda: repository,
                fallback_search=fallback,
            )
        )

    assert result["fallback_used"] is False
    assert result["fallback_skipped_reason"] == skip_reason
    fallback.assert_not_called()


def test_default_relevance_miss_preserves_github_fallback() -> None:
    fixture = load_catalog_cases()
    repository = ScriptedCatalogRepository(fixture, [{"project_keys": [], "total": 0}])
    fallback = MagicMock(return_value={"items": [], "total": 0})

    with patch.object(project_discovery.settings, "project_semantic_search_enabled", False):
        result = asyncio.run(
            project_discovery.search_projects(
                query="agent learning",
                mode="ai",
                repository_factory=lambda: repository,
                fallback_search=fallback,
            )
        )

    assert result["sort"] == "relevance"
    assert result["fallback_used"] is True
    assert fallback.call_args.kwargs["sort"] == "stars"


def test_semantic_timeout_preserves_github_fallback() -> None:
    fixture = load_catalog_cases()
    repository = ScriptedCatalogRepository(fixture, [{"project_keys": [], "total": 0}])
    fallback = MagicMock(return_value={"items": [], "total": 0})

    async def raise_timeout(awaitable: Any, *, timeout: float) -> None:
        awaitable.close()
        raise TimeoutError

    with (
        patch.object(project_discovery.settings, "project_semantic_search_enabled", True),
        patch.object(project_discovery.asyncio, "wait_for", side_effect=raise_timeout),
    ):
        result = asyncio.run(
            project_discovery.search_projects(
                query="agent runtime",
                mode="ai",
                sort="stars",
                repository_factory=lambda: repository,
                semantic_search_factory=MagicMock(),
                fallback_search=fallback,
            )
        )

    assert result["fallback_used"] is True
    assert result["fallback_reason"] == "local_zero_results"
    fallback.assert_called_once()


def test_fallback_success_and_error_provenance_are_frozen() -> None:
    fixture = load_catalog_cases()

    def run(fallback: Any) -> dict[str, Any]:
        repository = ScriptedCatalogRepository(fixture, [{"project_keys": [], "total": 0}])
        with patch.object(project_discovery.settings, "project_semantic_search_enabled", False):
            return asyncio.run(
                project_discovery.search_projects(
                    query="workflow",
                    mode="generic",
                    repository_factory=lambda: repository,
                    fallback_search=fallback,
                )
            )

    success = run(
        MagicMock(
            return_value={
                "items": [fixture["projects"]["beta"]],
                "github_total_count": 7,
                "queries": ["workflow stars:>=500"],
                "cache_hit": True,
            }
        )
    )
    assert success["result_origin"] == "github_api_fallback"
    assert success["fallback_used"] is True
    assert success["fallback_reason"] == "local_zero_results"
    assert success["github_total_count"] == 7
    assert success["fallback_cache_hit"] is True

    failed = run(MagicMock(side_effect=RuntimeError("github unavailable")))
    assert failed["result_origin"] == "aigc_news_local"
    assert failed["fallback_used"] is True
    assert failed["fallback_reason"] == "local_zero_results"
    assert failed["fallback_error"] == "GitHub fallback failed: github unavailable"


def test_rest_project_and_category_serialization_is_frozen() -> None:
    fixture = load_catalog_cases()
    projects = routes_github_projects._projects_response(
        {"items": [fixture["projects"]["alpha"]], "total": 2, "page": 1, "page_size": 1},
        min_stars=500,
        source="github",
        scope="all",
        category="rag_knowledge",
        subcategory="rag_framework",
        q="rag",
        sort="stars",
    ).model_dump(mode="json")
    categories = routes_github_projects._categories_response(
        fixture["categories"], min_stars=500, source="github"
    ).model_dump(mode="json")

    assert projects["has_next"] is True
    assert projects["items"][0]["repo_id"] == "acme/alpha"
    assert [item["slug"] for item in categories["items"][:3]] == ["all", "recommended", "today"]
    assert categories["total"] == 2
    assert categories["today_count"] == 1
    assert categories["recommended_count"] == 1
