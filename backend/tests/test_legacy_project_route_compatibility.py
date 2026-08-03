from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_github_projects, routes_mcp
from backend.app.api.dependencies import (
    get_application_repositories,
    get_briefing_repository,
    get_project_search_runtime,
)
from backend.app.core.auth import OptionalMcpUser, OptionalUser
from backend.app.services.mcp.inbound import tools as inbound_tools


PROJECT_RESULT = {
    "items": [
        {
            "id": "github:1",
            "full_name": "owner/agent-kit",
            "description": "Agent toolkit",
            "category_slug": "agents_automation",
            "subcategory_slug": "agent_frameworks",
            "tags": ["agent"],
            "language": "Python",
            "stars": 1200,
            "forks": 80,
            "is_recommended": True,
        }
    ],
    "total": 25,
    "page": 2,
    "page_size": 10,
}

CATEGORY_RESULT = {
    "items": [
        {
            "slug": "agents_automation",
            "name": "Agents & Automation",
            "count": 7,
            "children": [
                {"slug": "agent_frameworks", "name": "Agent Frameworks", "count": 4}
            ],
        }
    ],
    "total": 12,
    "today_count": 3,
    "recommended_count": 5,
}


def _project_routes_client(repository: MagicMock, *, user: dict | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(routes_github_projects.router, prefix="/api")
    app.dependency_overrides[OptionalUser] = lambda: user
    client = TestClient(app)
    client._legacy_repository_patch = patch.object(  # type: ignore[attr-defined]
        routes_github_projects,
        "get_project_catalog_repository",
        return_value=repository,
    )
    client._legacy_repository_patch.start()  # type: ignore[attr-defined]
    return client


def _close_project_routes_client(client: TestClient) -> None:
    client._legacy_repository_patch.stop()  # type: ignore[attr-defined]
    client.close()


def _mcp_client(*, user: dict | None = None) -> TestClient:
    app = FastAPI()
    repositories = SimpleNamespace(
        documents=MagicMock(),
        rank_snapshots=MagicMock(),
        project_collections=MagicMock(),
    )
    project_search_runtime = SimpleNamespace(search_projects=AsyncMock())
    app.dependency_overrides[get_briefing_repository] = lambda: MagicMock()
    app.dependency_overrides[get_application_repositories] = lambda: repositories
    app.dependency_overrides[get_project_search_runtime] = (
        lambda: project_search_runtime
    )
    app.dependency_overrides[OptionalMcpUser] = lambda: user
    app.include_router(routes_mcp.router, prefix="/api")
    client = TestClient(app)
    client._project_search_runtime = project_search_runtime  # type: ignore[attr-defined]
    return client


def _call_tool(client: TestClient, name: str, arguments: dict, request_id: int = 1):
    return client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )


def test_legacy_http_aliases_delegate_to_canonical_route_handlers() -> None:
    project_response = routes_github_projects.GitHubProjectsResponse(
        items=[],
        total=0,
        page=1,
        page_size=24,
        has_next=False,
        min_stars=500,
        scope="all",
        category="",
        subcategory="",
        q="",
        sort="stars",
        source="github",
    )
    category_response = routes_github_projects.GitHubProjectCategoriesResponse(
        items=[], total=0, min_stars=500, source="github"
    )
    with (
        patch.object(
            routes_github_projects,
            "list_projects",
            new=AsyncMock(return_value=project_response),
        ) as list_projects,
        patch.object(
            routes_github_projects,
            "list_project_categories",
            new=AsyncMock(return_value=category_response),
        ) as list_categories,
    ):
        projects = asyncio.run(
            routes_github_projects.list_github_projects(
                category=" agents ",
                subcategory=" frameworks ",
                q=" sdk ",
                language=" Python ",
                page=2,
                page_size=7,
                sort="updated",
            )
        )
        categories = asyncio.run(
            routes_github_projects.list_github_project_categories()
        )

    assert projects is project_response
    assert categories is category_response
    list_projects.assert_awaited_once_with(
        source="github",
        scope="all",
        category=" agents ",
        subcategory=" frameworks ",
        q=" sdk ",
        language=" Python ",
        page=2,
        page_size=7,
        sort="updated",
        user=None,
    )
    list_categories.assert_awaited_once_with(source="github", user=None)


def test_mcp_legacy_library_registry_aliases_canonical_ai_handler() -> None:
    assert (
        inbound_tools.MCP_TOOL_REGISTRY["get_project_library"]["handler"]
        is inbound_tools.MCP_TOOL_REGISTRY["search_github_ai_projects"]["handler"]
    )


def test_legacy_project_queries_cannot_reintroduce_duplicate_implementations() -> None:
    app_root = Path(__file__).parents[1] / "app"
    route_module = ast.parse(
        (app_root / "api" / "routes_github_projects.py").read_text(encoding="utf-8")
    )
    route_functions = {
        node.name: node
        for node in route_module.body
        if isinstance(node, ast.AsyncFunctionDef)
    }
    expected_alias_calls = {
        "list_github_projects": "list_projects",
        "list_github_project_categories": "list_project_categories",
    }
    for alias_name, canonical_name in expected_alias_calls.items():
        alias = route_functions[alias_name]
        assert len(alias.body) == 2
        return_statement = alias.body[-1]
        assert isinstance(return_statement, ast.Return)
        assert isinstance(return_statement.value, ast.Await)
        call = return_statement.value.value
        assert isinstance(call, ast.Call)
        assert isinstance(call.func, ast.Name)
        assert call.func.id == canonical_name

    tools_module = ast.parse(
        (app_root / "services" / "mcp" / "inbound" / "tools.py").read_text(
            encoding="utf-8"
        )
    )
    tool_functions = {
        node.name
        for node in tools_module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_tool_get_project_library" not in tool_functions
    assert "_public_project_item" not in tool_functions


def test_legacy_projects_defaults_preserve_public_github_wire_shape() -> None:
    repository = MagicMock()
    repository.list_projects.return_value = {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 24,
    }
    client = _project_routes_client(repository)
    try:
        response = client.get("/api/github/projects")
    finally:
        _close_project_routes_client(client)

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 24,
        "has_next": False,
        "min_stars": 500,
        "scope": "all",
        "category": "",
        "subcategory": "",
        "q": "",
        "sort": "stars",
        "source": "github",
    }
    repository.list_projects.assert_called_once_with(
        source="github",
        scope="all",
        category="",
        subcategory="",
        q="",
        language="",
        page=1,
        page_size=24,
        sort="stars",
        min_stars=500,
        enriched_only=True,
        user_id=None,
    )


def test_legacy_projects_match_canonical_query_filters_pagination_and_sort() -> None:
    repository = MagicMock()
    repository.list_projects.return_value = PROJECT_RESULT
    client = _project_routes_client(repository)
    query = (
        "category=%20agents_automation%20&subcategory=%20agent_frameworks%20"
        "&q=%20agent%20&language=%20Python%20&page=2&page_size=10&sort=updated"
    )
    try:
        legacy = client.get(f"/api/github/projects?{query}")
        canonical = client.get(f"/api/projects?source=github&scope=all&{query}")
    finally:
        _close_project_routes_client(client)

    assert legacy.status_code == canonical.status_code == 200
    assert legacy.json() == canonical.json()
    assert legacy.json()["has_next"] is True
    expected = {
        "source": "github",
        "scope": "all",
        "category": "agents_automation",
        "subcategory": "agent_frameworks",
        "q": "agent",
        "language": "Python",
        "page": 2,
        "page_size": 10,
        "sort": "updated",
        "min_stars": 500,
        "enriched_only": True,
        "user_id": None,
    }
    assert repository.list_projects.call_args_list[0].kwargs == expected
    assert repository.list_projects.call_args_list[1].kwargs == expected


def test_legacy_projects_remain_auth_neutral() -> None:
    repository = MagicMock()
    repository.list_projects.return_value = {
        "items": [], "total": 0, "page": 1, "page_size": 24
    }
    client = _project_routes_client(repository, user={"user_id": 42})
    try:
        legacy = client.get(
            "/api/github/projects",
            headers={"Authorization": "Bearer authenticated-test-token"},
        )
        canonical = client.get("/api/projects?source=github")
    finally:
        _close_project_routes_client(client)

    assert legacy.status_code == canonical.status_code == 200
    assert repository.list_projects.call_args_list[0].kwargs["user_id"] is None
    assert repository.list_projects.call_args_list[1].kwargs["user_id"] == 42


def test_legacy_categories_match_canonical_github_shape_and_filters() -> None:
    repository = MagicMock()
    repository.get_project_categories.return_value = CATEGORY_RESULT
    client = _project_routes_client(repository)
    try:
        legacy = client.get("/api/github/projects/categories")
        canonical = client.get("/api/projects/categories?source=github")
    finally:
        _close_project_routes_client(client)

    assert legacy.status_code == canonical.status_code == 200
    assert legacy.json() == canonical.json()
    payload = legacy.json()
    assert payload["items"][:3] == [
        {"slug": "all", "name": "全部", "name_zh": "全部", "name_en": "All", "count": 12, "kind": "scope", "scope": "all", "children": []},
        {"slug": "recommended", "name": "站长推荐", "name_zh": "站长推荐", "name_en": "Recommended", "count": 5, "kind": "scope", "scope": "recommended", "children": []},
        {"slug": "today", "name": "今日暴涨", "name_zh": "今日暴涨", "name_en": "Trending Today", "count": 3, "kind": "scope", "scope": "today", "children": []},
    ]
    assert payload["min_stars"] == 500
    assert payload["source"] == "github"
    assert repository.get_project_categories.call_count == 2
    for call in repository.get_project_categories.call_args_list:
        assert call.kwargs == {
            "source": "github",
            "min_stars": 500,
            "enriched_only": True,
        }


@pytest.mark.parametrize(
    ("path", "expected_status"),
    [
        ("/api/github/projects?page=0", 422),
        ("/api/github/projects?page_size=61", 422),
        ("/api/github/projects?sort=relevance", 422),
        ("/api/projects?source=website", 404),
        ("/api/projects/categories?source=website", 404),
    ],
)
def test_legacy_and_canonical_project_errors_remain_explicit(
    path: str, expected_status: int
) -> None:
    repository = MagicMock()
    client = _project_routes_client(repository)
    try:
        response = client.get(path)
    finally:
        _close_project_routes_client(client)

    assert response.status_code == expected_status
    repository.list_projects.assert_not_called()
    repository.get_project_categories.assert_not_called()


def test_get_project_library_matches_canonical_ai_tool_defaults_and_wire_shape() -> None:
    canonical_result = {
        "items": [{"id": "github:1", "full_name": "owner/agent-kit", "stars": 1200}],
        "total": 1,
        "page": 1,
        "page_size": 10,
        "has_next": False,
        "min_stars": 500,
        "scope": "all",
        "category": "",
        "subcategory": "",
        "language": "",
        "q": "",
        "sort": "stars",
        "source": "github",
        "search_mode": "ai",
        "result_origin": "aigc_news_local",
        "local_total": 1,
        "fallback_used": False,
        "fallback_reason": "",
        "fallback_skipped_reason": "",
        "fallback_policy": "local_first_github_only_when_semantics_preserved",
    }
    client = _mcp_client()
    search = client._project_search_runtime.search_projects  # type: ignore[attr-defined]
    search.return_value = canonical_result
    legacy = _call_tool(client, "get_project_library", {}, 1)
    canonical = _call_tool(client, "search_github_ai_projects", {}, 2)
    client.close()

    assert legacy.status_code == canonical.status_code == 200
    assert legacy.json()["result"] == canonical.json()["result"]
    assert legacy.json()["result"]["structuredContent"] == canonical_result
    assert search.await_count == 2
    for call in search.await_args_list:
        assert call.kwargs == {
            "query": "",
            "mode": "ai",
            "language": "",
            "client_intent": None,
            "category": "",
            "subcategory": "",
            "scope": "all",
            "sort": None,
            "page": 1,
            "limit": 10,
            "fallback_search": inbound_tools.search_github_projects_fallback,
        }


def test_get_project_library_matches_canonical_ai_filters_and_is_auth_neutral() -> None:
    arguments = {
        "q": " agent sdk ",
        "category": "agents_automation",
        "subcategory": "agent_frameworks",
        "language": "Python",
        "scope": "recommended",
        "sort": "recent",
        "page": 2,
        "limit": 7,
    }
    result = {"items": [], "total": 0, "page": 2, "page_size": 7}
    clients = [
        _mcp_client(),
        _mcp_client(user={"user_id": 42, "scopes": frozenset()}),
    ]
    searches = [
        client._project_search_runtime.search_projects  # type: ignore[attr-defined]
        for client in clients
    ]
    for search in searches:
        search.return_value = result
    anonymous = _call_tool(clients[0], "get_project_library", arguments, 1)
    authenticated = _call_tool(clients[1], "get_project_library", arguments, 2)
    canonical = _call_tool(clients[1], "search_github_ai_projects", arguments, 3)
    for client in clients:
        client.close()

    assert anonymous.json()["result"] == authenticated.json()["result"]
    assert authenticated.json()["result"] == canonical.json()["result"]
    assert searches[0].await_count == 1
    assert searches[1].await_count == 2
    for search in searches:
        for call in search.await_args_list:
            assert call.kwargs["query"] == "agent sdk"
            assert call.kwargs["category"] == "agents_automation"
            assert call.kwargs["subcategory"] == "agent_frameworks"
            assert call.kwargs["language"] == "Python"
            assert call.kwargs["scope"] == "recommended"
            assert call.kwargs["sort"] == "recent"
            assert call.kwargs["page"] == 2
            assert call.kwargs["limit"] == 7


@pytest.mark.parametrize(
    "arguments",
    [
        {"page": 0},
        {"limit": 21},
        {"sort": "invalid"},
        {"category": "not-a-category"},
        {"unexpected": True},
    ],
)
def test_get_project_library_preserves_canonical_ai_validation_errors(
    arguments: dict,
) -> None:
    client = _mcp_client()
    search = client._project_search_runtime.search_projects  # type: ignore[attr-defined]
    legacy = _call_tool(client, "get_project_library", arguments, 1)
    canonical = _call_tool(client, "search_github_ai_projects", arguments, 2)
    client.close()

    assert legacy.status_code == canonical.status_code == 200
    assert legacy.json()["result"]["isError"] is True
    assert canonical.json()["result"]["isError"] is True
    assert legacy.json()["result"]["content"] == canonical.json()["result"]["content"]
    search.assert_not_awaited()
