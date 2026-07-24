import asyncio
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock

repository_module = types.ModuleType("backend.app.repositories.mysql_repo")
repository_module.MySQLRepository = MagicMock
sys.modules.setdefault("backend.app.repositories.mysql_repo", repository_module)

config_module = types.ModuleType("backend.app.core.config")
config_module.settings = types.SimpleNamespace(
    mcp_github_fallback_enabled=True,
    mcp_github_fallback_use_token=False,
    mcp_github_fallback_timeout_seconds=8.0,
    project_semantic_search_enabled=False,
    project_semantic_query_timeout_seconds=6.0,
    project_reranker_enabled=False,
    project_reranker_candidate_limit=20,
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

    def test_relevance_search_fuses_lexical_and_semantic_candidates(self) -> None:
        class HybridRepository:
            def __init__(self) -> None:
                self.find_lexical_candidate_repo_ids = MagicMock(
                    return_value=["owner/lexical", "owner/shared"]
                )
                self.list_projects = MagicMock(
                    return_value={
                        "items": [{"id": "1", "full_name": "owner/shared", "stars": 800}],
                        "total": 1,
                    }
                )

        repo = HybridRepository()
        semantic = MagicMock()
        semantic.search_repo_ids.return_value = [
            types.SimpleNamespace(repo_id="owner/semantic", score=0.9),
            types.SimpleNamespace(repo_id="owner/shared", score=0.8),
        ]
        project_discovery.settings.project_semantic_search_enabled = True
        try:
            result = asyncio.run(
                project_discovery.search_projects(
                    query="智能体工作流",
                    mode="ai",
                    repository_factory=lambda: repo,
                    semantic_search_factory=lambda: semantic,
                )
            )
        finally:
            project_discovery.settings.project_semantic_search_enabled = False

        call = repo.list_projects.call_args.kwargs
        self.assertEqual(call["q"], "")
        self.assertEqual(call["sort"], "relevance")
        self.assertEqual(
            call["candidate_repo_ids"],
            ["owner/shared", "owner/semantic", "owner/lexical"],
        )
        self.assertEqual(result["sort"], "relevance")

    def test_host_intent_is_shared_by_lexical_and_semantic_search(self) -> None:
        class HybridRepository:
            def __init__(self) -> None:
                self.lexical_queries = []

            def find_lexical_candidate_repo_ids(self, **kwargs):
                self.lexical_queries.append(kwargs["q"])
                return ["owner/sdk"]

            def list_projects(self, **kwargs):
                return {
                    "items": [{"full_name": "owner/sdk", "stars": 800}],
                    "total": 1,
                }

        semantic = MagicMock()
        semantic.search_repo_ids.return_value = []
        repo = HybridRepository()
        project_discovery.settings.project_semantic_search_enabled = True
        try:
            asyncio.run(
                project_discovery.search_projects(
                    query="MCP Python SDK server examples",
                    mode="ai",
                    client_intent={
                        "language": "en",
                        "intent_class": "sdk",
                        "lexical_terms": ["MCP", "Python", "SDK"],
                        "semantic_queries": ["Model Context Protocol MCP Python SDK examples"],
                        "must_have": ["MCP", "Python"],
                    },
                    repository_factory=lambda: repo,
                    semantic_search_factory=lambda: semantic,
                )
            )
        finally:
            project_discovery.settings.project_semantic_search_enabled = False

        self.assertEqual(repo.lexical_queries, ["MCP Python SDK"])
        selected_intent = semantic.search_repo_ids.call_args.args[0]
        self.assertEqual(selected_intent.schema_version, "project-search-intent-client-v1")
        self.assertEqual(selected_intent.must_have, ("MCP", "Python"))

    def test_optional_reranker_reorders_hybrid_prefix(self) -> None:
        class HybridRepository:
            def __init__(self) -> None:
                self.calls = []

            def find_lexical_candidate_repo_ids(self, **_kwargs):
                return ["owner/a", "owner/b"]

            def list_projects(self, **kwargs):
                self.calls.append(kwargs)
                ordered = kwargs["candidate_repo_ids"]
                return {
                    "items": [
                        {"full_name": repo_id, "description": repo_id, "stars": 800}
                        for repo_id in ordered[: kwargs["page_size"]]
                    ],
                    "total": len(ordered),
                }

        repo = HybridRepository()
        reranker = MagicMock()
        reranker.rerank_repo_ids = AsyncMock(return_value=["owner/b", "owner/a"])
        project_discovery.settings.project_reranker_enabled = True
        try:
            result = asyncio.run(
                project_discovery.search_projects(
                    query="agent learning",
                    mode="ai",
                    repository_factory=lambda: repo,
                    reranker_factory=lambda: reranker,
                )
            )
        finally:
            project_discovery.settings.project_reranker_enabled = False

        self.assertEqual(
            [item["full_name"] for item in result["items"]],
            ["owner/b", "owner/a"],
        )
        self.assertEqual(repo.calls[-1]["candidate_repo_ids"], ["owner/b", "owner/a"])

    def test_host_intent_enriches_reranker_query_without_changing_filters(self) -> None:
        class HybridRepository:
            def __init__(self) -> None:
                self.calls = []

            def find_lexical_candidate_repo_ids(self, **_kwargs):
                return ["owner/a", "owner/b"]

            def list_projects(self, **kwargs):
                self.calls.append(kwargs)
                return {
                    "items": [{"full_name": repo_id} for repo_id in kwargs["candidate_repo_ids"]],
                    "total": len(kwargs["candidate_repo_ids"]),
                }

        repo = HybridRepository()
        reranker = MagicMock()
        reranker.rerank_repo_ids = AsyncMock(return_value=["owner/a", "owner/b"])
        project_discovery.settings.project_reranker_enabled = True
        try:
            asyncio.run(
                project_discovery.search_projects(
                    query="MCP Python SDK",
                    mode="ai",
                    language="Python",
                    category="agents_automation",
                    client_intent={
                        "language": "en",
                        "intent_class": "sdk",
                        "lexical_terms": ["MCP", "Python", "SDK"],
                        "semantic_queries": ["MCP Python SDK server examples"],
                        "artifact_types": ["SDK", "server"],
                        "must_have": ["MCP", "Python"],
                    },
                    repository_factory=lambda: repo,
                    reranker_factory=lambda: reranker,
                )
            )
        finally:
            project_discovery.settings.project_reranker_enabled = False

        reranker_query = reranker.rerank_repo_ids.call_args.args[0]
        self.assertIn("artifact types: SDK, server", reranker_query)
        self.assertIn("must have: MCP, Python", reranker_query)
        self.assertTrue(all(call["category"] == "agents_automation" for call in repo.calls))
        self.assertTrue(all(call["language"] == "Python" for call in repo.calls))

    def test_default_relevance_miss_uses_bounded_github_fallback(self) -> None:
        class HybridRepository:
            def find_lexical_candidate_repo_ids(self, **_kwargs):
                return []

            def list_projects(self, **_kwargs):
                return {"items": [], "total": 0}

        fallback = MagicMock(return_value={"items": [], "total": 0})
        result = asyncio.run(
            project_discovery.search_projects(
                query="agent learning",
                mode="ai",
                repository_factory=HybridRepository,
                fallback_search=fallback,
            )
        )

        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["sort"], "relevance")
        self.assertEqual(fallback.call_args.kwargs["sort"], "stars")

    def test_host_intent_fallback_keeps_original_query(self) -> None:
        class HybridRepository:
            def find_lexical_candidate_repo_ids(self, **_kwargs):
                return []

            def list_projects(self, **_kwargs):
                return {"items": [], "total": 0}

        fallback = MagicMock(return_value={"items": [], "total": 0})
        asyncio.run(
            project_discovery.search_projects(
                query="Python SDK",
                mode="ai",
                client_intent={
                    "language": "en",
                    "intent_class": "sdk",
                    "lexical_terms": ["MCP", "Python", "SDK"],
                    "semantic_queries": ["MCP Python SDK examples"],
                },
                repository_factory=HybridRepository,
                fallback_search=fallback,
            )
        )

        self.assertEqual(fallback.call_args.kwargs["q"], "Python SDK")

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
                    sort="stars",
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
        self.assertEqual(
            project_discovery.resolve_project_sort(
                "all",
                None,
                has_query=True,
                prefer_relevance=True,
            ),
            "relevance",
        )
        self.assertEqual(
            project_discovery.resolve_project_sort(
                "all",
                "stars",
                has_query=True,
                prefer_relevance=True,
            ),
            "stars",
        )
        self.assertEqual(
            project_discovery.resolve_project_sort(
                "all",
                "relevance",
                has_query=False,
                prefer_relevance=True,
            ),
            "stars",
        )
        self.assertEqual(project_discovery.resolve_project_sort("today", "relevance"), "hot")
        self.assertEqual(project_discovery.resolve_project_sort("recommended", None), "recent")


if __name__ == "__main__":
    unittest.main()
