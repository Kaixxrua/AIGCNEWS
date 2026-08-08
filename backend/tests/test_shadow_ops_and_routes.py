from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from backend.app.api import routes_github_projects, routes_ops
from backend.app.services.mcp.inbound import tools as inbound_tools
from backend.app.services.project_catalog.query_service import ProjectCatalogQueryService


def test_mcp_categories_use_catalog_factory() -> None:
    repository = MagicMock()
    repository.get_project_categories.return_value = {
        "items": [], "total": 0, "today_count": 0, "recommended_count": 0
    }
    factory = MagicMock(return_value=repository)
    context = MagicMock()
    context.catalog_queries = ProjectCatalogQueryService(repository_factory=factory)
    result = asyncio.run(inbound_tools._tool_get_project_categories(context, {}))
    factory.assert_called_once_with()
    assert result["source"] == "github"


def test_canonical_categories_use_catalog_factory() -> None:
    repository = MagicMock()
    repository.get_project_categories.return_value = {
        "items": [], "total": 0, "today_count": 0, "recommended_count": 0
    }
    factory = MagicMock(return_value=repository)
    catalog = ProjectCatalogQueryService(repository_factory=factory)
    result = asyncio.run(
        routes_github_projects.list_project_categories(
            source="all", user=None, catalog=catalog
        )
    )
    factory.assert_called_once_with()
    assert result.total == 0


def test_finalize_shadow_route_drains_search_epoch() -> None:
    search = {"epoch": "search-v2", "lifecycle": "finalized"}
    service = MagicMock()
    service.finalize_project_shadow = AsyncMock(return_value={"search": search})

    result = asyncio.run(
        routes_ops.finalize_project_shadow({"role": "admin"}, service)
    )

    assert result == {"search": search}
    service.finalize_project_shadow.assert_awaited_once_with()
