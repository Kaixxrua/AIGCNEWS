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
    project_semantic_search_enabled=False,
    project_semantic_query_timeout_seconds=3.0,
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

    def test_ai_sql_miss_uses_local_semantic_candidates_before_fallback(self) -> None:
        repo = MagicMock()
        repo.list_projects.side_effect = [
            {"items": [], "total": 0},
            {"items": [{"id": "1", "full_name": "owner/repo", "stars": 800}], "total": 1},
        ]
        semantic = MagicMock()
        semantic.search_repo_ids.return_value = [types.SimpleNamespace(repo_id="owner/repo", score=0.8)]
        fallback = MagicMock()
        project_discovery.settings.project_semantic_search_enabled = True
        try:
            result = asyncio.run(
                project_discovery.search_projects(
                    query="frontend development skills",
                    mode="ai",
                    repository_factory=lambda: repo,
                    semantic_search_factory=lambda: semantic,
                    fallback_search=fallback,
                )
            )
        finally:
            project_discovery.settings.project_semantic_search_enabled = False

        self.assertEqual(result["result_origin"], "aigc_news_local")
        self.assertEqual(result["local_total"], 1)
        self.assertFalse(result["fallback_used"])
        self.assertEqual(repo.list_projects.call_args_list[1].kwargs["candidate_repo_ids"], ["owner/repo"])
        self.assertEqual(repo.list_projects.call_args_list[1].kwargs["q"], "")
        fallback.assert_not_called()

    def test_semantic_failure_preserves_github_fallback(self) -> None:
        repo = MagicMock()
        repo.list_projects.return_value = {"items": [], "total": 0}
        semantic = MagicMock()
        semantic.search_repo_ids.side_effect = RuntimeError("milvus down")
        fallback = MagicMock(return_value={"items": [], "total": 0})
        project_discovery.settings.project_semantic_search_enabled = True
        try:
            result = asyncio.run(
                project_discovery.search_projects(
                    query="agent tooling",
                    mode="ai",
                    repository_factory=lambda: repo,
                    semantic_search_factory=lambda: semantic,
                    fallback_search=fallback,
                )
            )
        finally:
            project_discovery.settings.project_semantic_search_enabled = False

        self.assertTrue(result["fallback_used"])
        fallback.assert_called_once()

    def test_generic_search_never_calls_semantic_search(self) -> None:
        repo = MagicMock()
        repo.list_projects.return_value = {"items": [], "total": 0}
        semantic = MagicMock()
        fallback = MagicMock(return_value={"items": [], "total": 0})
        project_discovery.settings.project_semantic_search_enabled = True
        try:
            asyncio.run(
                project_discovery.search_projects(
                    query="screenshot",
                    mode="generic",
                    repository_factory=lambda: repo,
                    semantic_search_factory=lambda: semantic,
                    fallback_search=fallback,
                )
            )
        finally:
            project_discovery.settings.project_semantic_search_enabled = False
        semantic.assert_not_called()

    def test_scope_defaults_resolve_consistently(self) -> None:
        self.assertEqual(project_discovery.resolve_project_sort("all", None), "stars")
        self.assertEqual(project_discovery.resolve_project_sort("today", "name"), "hot")
        self.assertEqual(project_discovery.resolve_project_sort("recommended", None), "recent")


if __name__ == "__main__":
    unittest.main()
