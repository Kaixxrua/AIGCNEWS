import asyncio
import sys
import types
import unittest
from unittest.mock import MagicMock

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


class ProjectDiscoveryTests(unittest.TestCase):
    def test_local_hits_suppress_fallback(self) -> None:
        repo = MagicMock()
        repo.list_projects.return_value = {
            "items": [{"id": "1", "full_name": "a/b", "stars": 100}],
            "total": 1,
        }
        fallback = MagicMock()
        result = asyncio.run(
            project_discovery.search_projects(
                query="screenshot",
                mode="generic",
                limit=5,
                repository_factory=lambda: repo,
                fallback_search=fallback,
            )
        )
        self.assertEqual(result["local_total"], 1)
        self.assertFalse(result["fallback_used"])
        fallback.assert_not_called()

    def test_empty_local_uses_generic_fallback(self) -> None:
        repo = MagicMock()
        repo.list_projects.return_value = {"items": [], "total": 0}
        fallback_result = {
            "items": [{"id": "x", "full_name": "x/y", "result_origin": "github_api_fallback"}],
            "total": 1,
            "queries": ["screenshot stars:>=50"],
        }
        fallback = MagicMock(return_value=fallback_result)
        result = asyncio.run(
            project_discovery.search_projects(
                query="screenshot",
                mode="generic",
                limit=5,
                repository_factory=lambda: repo,
                fallback_search=fallback,
            )
        )
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["result_origin"], "github_api_fallback")
        self.assertEqual(fallback.call_args.kwargs["mode"], "generic")
        self.assertEqual(fallback.call_args.kwargs["min_stars"], 50)

    def test_today_scope_never_falls_back(self) -> None:
        repo = MagicMock()
        repo.list_projects.return_value = {"items": [], "total": 0}
        fallback = MagicMock()
        result = asyncio.run(
            project_discovery.search_projects(
                query="rag",
                mode="ai",
                scope="today",
                repository_factory=lambda: repo,
                fallback_search=fallback,
            )
        )
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["fallback_skipped_reason"], "scope_requires_local_metrics")
        fallback.assert_not_called()

    def test_local_total_suppresses_fallback_even_when_page_is_empty(self) -> None:
        repo = MagicMock()
        repo.list_projects.return_value = {"items": [], "total": 7}
        fallback = MagicMock()
        result = asyncio.run(
            project_discovery.search_projects(
                query="screenshot",
                mode="generic",
                page=2,
                limit=5,
                repository_factory=lambda: repo,
                fallback_search=fallback,
            )
        )
        self.assertEqual(result["local_total"], 7)
        self.assertEqual(result["page"], 2)
        self.assertFalse(result["fallback_used"])
        fallback.assert_not_called()

    def test_taxonomy_filter_skips_lossy_fallback(self) -> None:
        repo = MagicMock()
        repo.list_projects.return_value = {"items": [], "total": 0}
        fallback = MagicMock()
        result = asyncio.run(
            project_discovery.search_projects(
                query="agent",
                mode="ai",
                category="agents_automation",
                repository_factory=lambda: repo,
                fallback_search=fallback,
            )
        )
        self.assertEqual(
            result["fallback_skipped_reason"],
            "taxonomy_filter_requires_local_classification",
        )
        fallback.assert_not_called()

    def test_scope_defaults_resolve_consistently(self) -> None:
        self.assertEqual(project_discovery.resolve_project_sort("all", None), "stars")
        self.assertEqual(project_discovery.resolve_project_sort("today", "name"), "hot")
        self.assertEqual(project_discovery.resolve_project_sort("recommended", None), "recent")


if __name__ == "__main__":
    unittest.main()
