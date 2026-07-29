from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from backend.app.api import routes_github_projects, routes_mcp, routes_ops
from backend.app.services.mcp.inbound import tools as inbound_tools


def test_mcp_categories_use_catalog_factory() -> None:
    repository = MagicMock()
    repository.get_project_categories.return_value = {
        "items": [], "total": 0, "today_count": 0, "recommended_count": 0
    }
    with patch.object(inbound_tools, "get_project_catalog_repository", return_value=repository) as factory:
        result = asyncio.run(routes_mcp._tool_get_project_categories(MagicMock(), {}))
    factory.assert_called_once_with()
    assert result["source"] == "github"


def test_legacy_categories_use_catalog_factory() -> None:
    repository = MagicMock()
    repository.get_project_categories.return_value = {
        "items": [], "total": 0, "today_count": 0, "recommended_count": 0
    }
    with patch.object(routes_github_projects, "get_project_catalog_repository", return_value=repository) as factory:
        result = asyncio.run(routes_github_projects.list_github_project_categories())
    factory.assert_called_once_with()
    assert result.total == 0


def test_shadow_status_route_is_admin_dependency_and_sanitized() -> None:
    snapshot = {
        "enabled": True,
        "active_backend": "mysql",
        "recent_cases": [{"argument_sha256": "a" * 64, "outcome": "match"}],
    }
    with patch(
        "backend.app.services.project_catalog_shadow.project_catalog_shadow_snapshot",
        return_value=snapshot,
    ):
        result = asyncio.run(routes_ops.project_catalog_shadow_status({"role": "admin"}))
    assert result == snapshot
    assert "password" not in str(result)


def test_finalize_shadow_route_drains_both_named_epochs() -> None:
    catalog = {"epoch": "catalog-v2", "lifecycle": "finalized"}
    search = {"epoch": "search-v2", "lifecycle": "finalized"}
    with (
        patch(
            "backend.app.services.project_catalog_shadow.finalize_project_catalog_shadow",
            return_value=catalog,
        ) as finalize_catalog,
        patch(
            "backend.app.services.project_search_shadow.finalize_project_search_shadow",
            return_value=search,
        ) as finalize_search,
    ):
        result = asyncio.run(routes_ops.finalize_project_shadow({"role": "admin"}))

    assert result == {"catalog": catalog, "search": search}
    finalize_catalog.assert_called_once()
    finalize_search.assert_called_once()
