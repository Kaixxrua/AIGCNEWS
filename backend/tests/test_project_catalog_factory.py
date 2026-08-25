from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from backend.app.api import routes_github_projects
from backend.app.repositories import project_catalog_factory
from backend.app.services import project_discovery
from backend.app.services.project_catalog.query_service import ProjectCatalogQueryService


def test_factory_builds_postgres_adapter() -> None:
    adapter = MagicMock()

    with patch.object(
        project_catalog_factory,
        "PostgresProjectCatalogRepository",
        return_value=adapter,
    ) as adapter_type:
        result = project_catalog_factory.get_project_catalog_repository()

    assert result is adapter
    adapter_type.assert_called_once_with()


def test_discovery_uses_lazy_catalog_factory_by_default() -> None:
    repository = MagicMock()
    repository.list_projects.return_value = {"items": [], "total": 0}
    fallback = MagicMock(return_value={"items": [], "total": 0})

    with (
        patch.object(project_discovery, "get_project_catalog_repository", return_value=repository) as factory,
        patch.object(project_discovery.settings, "project_semantic_search_enabled", False),
    ):
        result = asyncio.run(
            project_discovery.search_projects(query="workflow", fallback_search=fallback)
        )

    factory.assert_called_once_with()
    repository.list_projects.assert_called_once()
    assert result["fallback_used"] is True


def test_explicit_discovery_repository_factory_takes_precedence() -> None:
    repository = MagicMock()
    repository.list_projects.return_value = {"items": [{"id": "github:a/b"}], "total": 1}

    with patch.object(project_discovery, "get_project_catalog_repository") as factory:
        result = asyncio.run(
            project_discovery.search_projects(
                query="workflow",
                repository_factory=lambda: repository,
            )
        )

    factory.assert_not_called()
    assert result["total"] == 1


def test_public_rest_project_handlers_use_catalog_factory() -> None:
    repository = MagicMock()
    repository.list_projects.return_value = {"items": [], "total": 0, "page": 1, "page_size": 24}
    repository.get_project_categories.return_value = {
        "items": [],
        "total": 0,
        "today_count": 0,
        "recommended_count": 0,
    }

    factory = MagicMock(return_value=repository)
    catalog = ProjectCatalogQueryService(repository_factory=factory)
    projects = asyncio.run(
        routes_github_projects.list_projects(
            source="all",
            scope="all",
            category="",
            subcategory="",
            q="",
            language="",
            page=1,
            page_size=24,
            sort=None,
            user=None,
            catalog=catalog,
        )
    )
    categories = asyncio.run(
        routes_github_projects.list_project_categories(
            source="all", user=None, catalog=catalog
        )
    )

    assert factory.call_count == 2
    assert projects.total == 0
    assert categories.total == 0
    repository.list_projects.assert_called_once()
    repository.get_project_categories.assert_called_once_with(
        source="github",
        min_stars=500,
        enriched_only=True,
    )


def test_github_library_total_uses_dedicated_count() -> None:
    repository = MagicMock()
    repository.count_github_catalog_candidates.return_value = 18776

    service = ProjectCatalogQueryService(repository_factory=lambda: repository)

    assert asyncio.run(service.github_library_total()) == 18776
    repository.count_github_catalog_candidates.assert_called_once_with(min_stars=500)
    repository.list_projects.assert_not_called()
