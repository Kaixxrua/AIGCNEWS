from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.api import routes_github_projects, routes_mcp
from backend.app.repositories import project_catalog_factory
from backend.app.services import project_discovery
from backend.app.services.mcp.inbound import tools as inbound_tools


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


def test_mcp_project_search_does_not_pin_mysql_repository() -> None:
    search = AsyncMock(return_value={"items": [], "total": 0})

    with patch.object(inbound_tools, "search_projects", search):
        asyncio.run(inbound_tools._search_project_library({"q": "workflow"}, mode="generic"))

    assert "repository_factory" not in search.call_args.kwargs


def test_public_rest_project_handlers_use_catalog_factory() -> None:
    repository = MagicMock()
    repository.list_projects.return_value = {"items": [], "total": 0, "page": 1, "page_size": 24}
    repository.get_project_categories.return_value = {
        "items": [],
        "total": 0,
        "today_count": 0,
        "recommended_count": 0,
    }

    with patch.object(
        routes_github_projects,
        "get_project_catalog_repository",
        return_value=repository,
    ) as factory:
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
            )
        )
        categories = asyncio.run(
            routes_github_projects.list_project_categories(source="all", user=None)
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
