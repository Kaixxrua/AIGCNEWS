import asyncio
import sys
import types
from unittest.mock import MagicMock, patch

repository_module = types.ModuleType("backend.app.repositories.mysql_repo")
repository_module.MySQLRepository = MagicMock
sys.modules.setdefault("backend.app.repositories.mysql_repo", repository_module)

config_module = types.ModuleType("backend.app.core.config")
config_module.settings = types.SimpleNamespace(
    mcp_github_fallback_enabled=True,
    mcp_github_fallback_use_token=False,
    mcp_github_fallback_timeout_seconds=8.0,
    github_token="",
)
sys.modules.setdefault("backend.app.core.config", config_module)

from backend.app.services import project_discovery


def test_local_hits_suppress_fallback():
    repo = MagicMock()
    repo.list_projects.return_value = {"items": [{"id": "1", "full_name": "a/b", "stars": 100}], "total": 1}
    fallback = MagicMock()
    result = asyncio.run(project_discovery.search_projects(query="screenshot", mode="generic", limit=5, repository_factory=lambda: repo, fallback_search=fallback))
    assert result["local_total"] == 1
    assert not result["fallback_used"]
    fallback.assert_not_called()


def test_empty_local_uses_generic_fallback():
    repo = MagicMock()
    repo.list_projects.return_value = {"items": [], "total": 0}
    fallback_result = {"items": [{"id": "x", "full_name": "x/y", "result_origin": "github_api_fallback"}], "total": 1, "queries": ["screenshot stars:>=50"]}
    fallback = MagicMock(return_value=fallback_result)
    result = asyncio.run(project_discovery.search_projects(query="screenshot", mode="generic", limit=5, repository_factory=lambda: repo, fallback_search=fallback))
    assert result["fallback_used"]
    assert result["result_origin"] == "github_api_fallback"
    assert fallback.call_args.kwargs["mode"] == "generic"
    assert fallback.call_args.kwargs["min_stars"] == 50


def test_today_scope_never_falls_back():
    repo = MagicMock()
    repo.list_projects.return_value = {"items": [], "total": 0}
    fallback = MagicMock()
    result = asyncio.run(project_discovery.search_projects(query="rag", mode="ai", scope="today", repository_factory=lambda: repo, fallback_search=fallback))
    assert not result["fallback_used"]
    fallback.assert_not_called()
