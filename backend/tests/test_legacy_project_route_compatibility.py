from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_mcp
from backend.app.api.dependencies import (
    get_application_repositories,
    get_briefing_repository,
    get_project_search_runtime,
)
from backend.app.core.auth import OptionalMcpUser
from backend.app.services.mcp.inbound import tools as inbound_tools


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


def test_mcp_legacy_library_registry_aliases_canonical_ai_handler() -> None:
    assert (
        inbound_tools.MCP_TOOL_REGISTRY["get_project_library"]["handler"]
        is inbound_tools.MCP_TOOL_REGISTRY["search_github_ai_projects"]["handler"]
    )


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
        {"language": "en"},
        {"language": "中文"},
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
