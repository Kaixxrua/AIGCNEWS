import asyncio
import types
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.repositories.project_catalog import (
    ProjectLexicalCandidate,
    ProjectLexicalCandidateLanes,
)
from backend.app.services import project_discovery


class ProjectDiscoveryTests(unittest.TestCase):
    def test_local_hits_suppress_fallback(self) -> None:
        repo = MagicMock()
        repo.list_projects.return_value = {
            "items": [{"id": "1", "full_name": "a/b", "stars": 500}],
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
        self.assertEqual(repo.list_projects.call_args.kwargs["min_stars"], 500)
        self.assertFalse(result["fallback_used"])
        fallback.assert_not_called()

    def test_empty_local_uses_generic_fallback(self) -> None:
        repo = MagicMock()
        repo.list_projects.return_value = {"items": [], "total": 0}
        fallback_result = {
            "items": [{"id": "x", "full_name": "x/y", "result_origin": "github_api_fallback"}],
            "total": 1,
            "queries": ["screenshot stars:>=500"],
        }
        fallback = MagicMock(return_value=fallback_result)
        with patch.object(project_discovery.settings, "project_semantic_search_enabled", False):
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
        self.assertEqual(fallback.call_args.kwargs["min_stars"], 500)

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
        self.assertEqual(
            repo.find_lexical_candidate_repo_ids.call_args.kwargs["q"],
            "智能体工作流",
        )
        selected_intent = semantic.search_repo_ids.call_args.args[0]
        self.assertEqual(selected_intent.concept_ids, ("workflow",))

    def test_v2_strategy_uses_typed_lanes_and_exact_lookup_protection(self) -> None:
        class V2Repository:
            def __init__(self) -> None:
                self.find_lexical_candidate_repo_ids = MagicMock(return_value=[])
                self.find_lexical_candidate_lanes = MagicMock(
                    return_value=ProjectLexicalCandidateLanes(
                        strict=(
                            ProjectLexicalCandidate(
                                "owner/popular", "strict", term_coverage=2, match_strength=3
                            ),
                        ),
                        relaxed=(
                            ProjectLexicalCandidate(
                                "DeusData/codebase-memory-mcp",
                                "relaxed",
                                term_coverage=1,
                                match_strength=1,
                            ),
                        ),
                    )
                )
                self.list_projects = MagicMock(
                    return_value={
                        "items": [{"full_name": "DeusData/codebase-memory-mcp", "stars": 900}],
                        "total": 1,
                    }
                )

        repo = V2Repository()
        project_discovery.settings.project_ai_search_strategy = "v2"
        try:
            asyncio.run(
                project_discovery.search_projects(
                    query="DeusData/codebase-memory-mcp",
                    mode="ai",
                    repository_factory=lambda: repo,
                )
            )
        finally:
            project_discovery.settings.project_ai_search_strategy = "legacy"

        repo.find_lexical_candidate_repo_ids.assert_not_called()
        repo.find_lexical_candidate_lanes.assert_called_once()
        plan = repo.find_lexical_candidate_lanes.call_args.kwargs["q"]
        self.assertEqual(plan.normalized_query, "DeusData/codebase-memory-mcp")
        # mcp 概念在 "-mcp" 后缀上按词边界命中并消费该 span，
        # 因此字面词只剩 owner 段；概念组负责 mcp 语义。
        self.assertEqual(plan.strict_terms, ("DeusData",))
        self.assertEqual({concept.concept_id for concept in plan.concepts}, {"mcp"})
        self.assertEqual(
            repo.list_projects.call_args.kwargs["candidate_repo_ids"][0],
            "DeusData/codebase-memory-mcp",
        )

    def test_shadow_strategy_keeps_legacy_authority(self) -> None:
        class ShadowRepository:
            def find_lexical_candidate_repo_ids(self, **_kwargs):
                return ["owner/legacy"]

            def find_lexical_candidate_lanes(self, **_kwargs):
                return ProjectLexicalCandidateLanes(
                    strict=(ProjectLexicalCandidate("owner/strict", "strict", 2, 2),),
                    relaxed=(ProjectLexicalCandidate("owner/relaxed", "relaxed", 1, 1),),
                )

            def list_projects(self, **kwargs):
                return {
                    "items": [{"full_name": kwargs["candidate_repo_ids"][0], "stars": 800}],
                    "total": 1,
                }

        manager = MagicMock()
        project_discovery.settings.project_ai_search_strategy = "shadow"
        try:
            result = asyncio.run(
                project_discovery.search_projects(
                    query="agent learning",
                    mode="ai",
                    repository_factory=ShadowRepository,
                    shadow_manager_factory=lambda: manager,
                )
            )
        finally:
            project_discovery.settings.project_ai_search_strategy = "legacy"

        self.assertEqual(result["items"][0]["full_name"], "owner/legacy")
        manager.submit.assert_called_once()
        self.assertEqual(manager.submit.call_args.kwargs["legacy_repo_ids"], ["owner/legacy"])
        self.assertIsNone(manager.submit.call_args.kwargs.get("lanes"))
        self.assertTrue(callable(manager.submit.call_args.kwargs["lanes_call"]))

    def test_explicit_non_relevance_sort_does_not_activate_v2(self) -> None:
        repo = MagicMock()
        repo.list_projects.return_value = {"items": [], "total": 0}
        project_discovery.settings.project_ai_search_strategy = "v2"
        try:
            asyncio.run(
                project_discovery.search_projects(
                    query="agent",
                    mode="ai",
                    sort="stars",
                    repository_factory=lambda: repo,
                    fallback_search=MagicMock(return_value={"items": [], "total": 0}),
                )
            )
        finally:
            project_discovery.settings.project_ai_search_strategy = "legacy"

        self.assertEqual(repo.list_projects.call_args.kwargs["q"], "agent")

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

    def test_generic_search_uses_semantic_retry_when_no_lexical_candidates(self) -> None:
        repo = MagicMock()
        repo.list_projects.return_value = {"items": [], "total": 0}
        semantic = MagicMock()
        semantic.search_repo_ids.return_value = []
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
        semantic.search_repo_ids.assert_called_once()
        fallback.assert_called_once()

    def test_generic_relevance_search_fuses_lexical_and_semantic_candidates(self) -> None:
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
                    mode="generic",
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
        self.assertEqual(result["search_mode"], "generic")
        selected_intent = semantic.search_repo_ids.call_args.args[0]
        self.assertEqual(selected_intent.schema_version, "project-search-intent-v1")
        self.assertEqual(selected_intent.concept_ids, ("workflow",))

    def test_generic_explicit_sort_keeps_legacy_keyword_search(self) -> None:
        class HybridRepository:
            def __init__(self) -> None:
                self.find_lexical_candidate_repo_ids = MagicMock(return_value=["owner/lexical"])
                self.list_projects = MagicMock(
                    return_value={
                        "items": [{"id": "1", "full_name": "owner/tool", "stars": 900}],
                        "total": 1,
                    }
                )

        repo = HybridRepository()
        fallback = MagicMock()
        result = asyncio.run(
            project_discovery.search_projects(
                query="screenshot",
                mode="generic",
                sort="stars",
                repository_factory=lambda: repo,
                fallback_search=fallback,
            )
        )

        repo.find_lexical_candidate_repo_ids.assert_not_called()
        call = repo.list_projects.call_args.kwargs
        self.assertEqual(call["q"], "screenshot")
        self.assertEqual(call["sort"], "stars")
        self.assertEqual(result["sort"], "stars")
        fallback.assert_not_called()

    def test_generic_v2_strategy_uses_exact_lookup_protection(self) -> None:
        class V2Repository:
            def __init__(self) -> None:
                self.find_lexical_candidate_repo_ids = MagicMock(return_value=[])
                self.find_lexical_candidate_lanes = MagicMock(
                    return_value=ProjectLexicalCandidateLanes(
                        strict=(
                            ProjectLexicalCandidate(
                                "owner/popular", "strict", term_coverage=2, match_strength=3
                            ),
                        ),
                        relaxed=(
                            ProjectLexicalCandidate(
                                "owner/exact-tool",
                                "relaxed",
                                term_coverage=1,
                                match_strength=1,
                            ),
                        ),
                    )
                )
                self.list_projects = MagicMock(
                    return_value={
                        "items": [{"full_name": "owner/exact-tool", "stars": 900}],
                        "total": 1,
                    }
                )

        repo = V2Repository()
        project_discovery.settings.project_ai_search_strategy = "v2"
        try:
            asyncio.run(
                project_discovery.search_projects(
                    query="owner/exact-tool",
                    mode="generic",
                    repository_factory=lambda: repo,
                )
            )
        finally:
            project_discovery.settings.project_ai_search_strategy = "legacy"

        repo.find_lexical_candidate_repo_ids.assert_not_called()
        repo.find_lexical_candidate_lanes.assert_called_once()
        self.assertEqual(
            repo.list_projects.call_args.kwargs["candidate_repo_ids"][0],
            "owner/exact-tool",
        )

    def _run_v2_adoption_search(self, repo: Any) -> list[str]:
        original_strategy = project_discovery.settings.project_ai_search_strategy
        original_weight = project_discovery.settings.project_search_adoption_weight
        original_semantic = project_discovery.settings.project_semantic_search_enabled
        project_discovery.settings.project_ai_search_strategy = "v2"
        project_discovery.settings.project_search_adoption_weight = 0.006
        project_discovery.settings.project_semantic_search_enabled = False
        try:
            asyncio.run(
                project_discovery.search_projects(
                    query="AI coding agent CLI",
                    mode="ai",
                    repository_factory=lambda: repo,
                )
            )
        finally:
            project_discovery.settings.project_ai_search_strategy = original_strategy
            project_discovery.settings.project_search_adoption_weight = original_weight
            project_discovery.settings.project_semantic_search_enabled = original_semantic
        return repo.list_projects.call_args.kwargs["candidate_repo_ids"]

    def _build_v2_adoption_repository(self, *, with_stars_map: bool) -> Any:
        class AdoptionRepository:
            def __init__(self) -> None:
                self.find_lexical_candidate_repo_ids = MagicMock(return_value=[])
                self.find_lexical_candidate_lanes = MagicMock(
                    return_value=ProjectLexicalCandidateLanes(
                        strict=(
                            ProjectLexicalCandidate(
                                "owner/fresh-fit", "strict", term_coverage=3
                            ),
                        ),
                        relaxed=tuple(
                            ProjectLexicalCandidate(
                                f"owner/filler-{index}", "relaxed", term_coverage=1
                            )
                            for index in range(29)
                        )
                        + (
                            ProjectLexicalCandidate(
                                "owner/veteran", "relaxed", term_coverage=1
                            ),
                        ),
                    )
                )
                if with_stars_map:
                    self.get_project_stars_map = MagicMock(
                        return_value={
                            "owner/veteran": 106_000,
                            "owner/fresh-fit": 20_000,
                            **{
                                f"owner/filler-{index}": 800
                                for index in range(29)
                            },
                        }
                    )
                self.list_projects = MagicMock(
                    return_value={
                        "items": [{"full_name": "owner/fresh-fit", "stars": 20_000}],
                        "total": 1,
                    }
                )

        return AdoptionRepository()

    def test_v2_strategy_adoption_stars_rescue_buried_high_star_candidate(self) -> None:
        without_stars = self._run_v2_adoption_search(
            self._build_v2_adoption_repository(with_stars_map=False)
        )
        with_stars = self._run_v2_adoption_search(
            self._build_v2_adoption_repository(with_stars_map=True)
        )

        # 无星数来源时保持纯拟合行为：元老只有 deep relaxed 单 lane，被埋
        self.assertGreater(without_stars.index("owner/veteran"), 4)
        # 有采用度压舱石时：元老被救到第 2 位，拟合冠军仍居首
        self.assertEqual(with_stars[0], "owner/fresh-fit")
        self.assertEqual(with_stars[1], "owner/veteran")
        self.assertEqual(set(with_stars), set(without_stars))

    def test_v2_strategy_adoption_lookup_failure_falls_back_to_fit_only(self) -> None:
        repo = self._build_v2_adoption_repository(with_stars_map=True)
        repo.get_project_stars_map = MagicMock(side_effect=RuntimeError("pg down"))

        ranked = self._run_v2_adoption_search(repo)

        self.assertEqual(ranked[0], "owner/fresh-fit")
        self.assertGreater(ranked.index("owner/veteran"), 4)

    def _run_v2_semantic_heat_search(
        self,
        repo: Any,
        *,
        heat_first: bool,
        query: str = "AI coding agent CLI",
    ) -> list[str]:
        semantic_search = MagicMock()
        semantic_search.search_repo_ids = MagicMock(
            return_value=[
                types.SimpleNamespace(repo_id="owner/veteran"),
                types.SimpleNamespace(repo_id="owner/deep-sem"),
            ]
        )
        originals = (
            project_discovery.settings.project_ai_search_strategy,
            project_discovery.settings.project_semantic_search_enabled,
            project_discovery.settings.project_semantic_heat_first,
        )
        project_discovery.settings.project_ai_search_strategy = "v2"
        project_discovery.settings.project_semantic_search_enabled = True
        project_discovery.settings.project_semantic_heat_first = heat_first
        try:
            asyncio.run(
                project_discovery.search_projects(
                    query=query,
                    mode="generic",
                    repository_factory=lambda: repo,
                    semantic_search_factory=lambda: semantic_search,
                )
            )
        finally:
            (
                project_discovery.settings.project_ai_search_strategy,
                project_discovery.settings.project_semantic_search_enabled,
                project_discovery.settings.project_semantic_heat_first,
            ) = originals
        return repo.list_projects.call_args.kwargs["candidate_repo_ids"]

    def _build_v2_semantic_repository(self) -> Any:
        class SemanticRepository:
            def __init__(self) -> None:
                self.find_lexical_candidate_repo_ids = MagicMock(return_value=[])
                self.find_lexical_candidate_lanes = MagicMock(
                    return_value=ProjectLexicalCandidateLanes(
                        strict=(
                            ProjectLexicalCandidate(
                                "owner/fit", "strict", term_coverage=3, match_strength=3
                            ),
                        ),
                        relaxed=(
                            ProjectLexicalCandidate(
                                "owner/veteran", "relaxed", term_coverage=1, match_strength=1
                            ),
                        ),
                    )
                )
                self.get_project_stars_map = MagicMock(
                    return_value={
                        "owner/veteran": 106_000,
                        "owner/deep-sem": 30_000,
                        "owner/fit": 20_000,
                    }
                )
                self.get_project_heat_map = MagicMock(
                    return_value={
                        # (hot_score v5, daily_star_growth, stars)
                        "owner/veteran": (85.5, 300, 106_000),
                        "owner/deep-sem": (12.0, 50, 30_000),
                        "owner/fit": (0.0, 0, 20_000),
                    }
                )
                self.list_projects = MagicMock(
                    return_value={
                        "items": [{"full_name": "owner/veteran", "stars": 106_000}],
                        "total": 1,
                    }
                )

        return SemanticRepository()

    def test_v2_semantic_lane_defaults_to_heat_order(self) -> None:
        ranked = self._run_v2_semantic_heat_search(
            self._build_v2_semantic_repository(), heat_first=True
        )

        # 热度（hot_score v5）优先：85.5 分元老登顶，12 分语义独苗压过
        # 当日无热度的拟合冠军（其 20k stars 只在同热度时兜底）
        self.assertEqual(ranked, ["owner/veteran", "owner/deep-sem", "owner/fit"])

    def test_v2_semantic_heat_order_keeps_exact_match_first(self) -> None:
        ranked = self._run_v2_semantic_heat_search(
            self._build_v2_semantic_repository(),
            heat_first=True,
            query="owner/fit",
        )

        # 精确命中力压 85.5 分热度冠军钉在榜首
        self.assertEqual(ranked[0], "owner/fit")
        self.assertEqual(ranked[1], "owner/veteran")

    def test_v2_semantic_heat_first_disabled_keeps_fit_order(self) -> None:
        ranked = self._run_v2_semantic_heat_search(
            self._build_v2_semantic_repository(), heat_first=False
        )

        self.assertEqual(ranked, ["owner/veteran", "owner/fit", "owner/deep-sem"])

    def test_v2_semantic_heat_lookup_failure_falls_back_to_fit_order(self) -> None:
        repo = self._build_v2_semantic_repository()
        repo.get_project_heat_map = MagicMock(side_effect=RuntimeError("pg down"))

        ranked = self._run_v2_semantic_heat_search(repo, heat_first=True)

        self.assertEqual(ranked, ["owner/veteran", "owner/fit", "owner/deep-sem"])

    def test_normalize_request_generic_mode_discards_taxonomy_and_scope(self) -> None:
        request = project_discovery._normalize_search_request(
            query="agent",
            mode="generic",
            language=" Python ",
            client_intent={"language": "en"},
            category="agents_automation",
            subcategory="agent_framework",
            scope="today",
            sort=None,
            page=0,
            limit=100,
        )
        self.assertEqual(request.category, "")
        self.assertEqual(request.subcategory, "")
        self.assertEqual(request.scope, "all")
        self.assertEqual(request.language, "Python")
        self.assertEqual(request.page, 1)
        self.assertEqual(request.limit, 20)
        self.assertFalse(request.client_intent_used)

    def test_normalize_request_uses_host_intent_only_for_ai_relevance(self) -> None:
        request = project_discovery._normalize_search_request(
            query="MCP Python SDK",
            mode="ai",
            language="",
            client_intent={
                "language": "en",
                "intent_class": "sdk",
                "lexical_terms": ["MCP", "Python", "SDK"],
                "semantic_queries": ["MCP Python SDK examples"],
                "must_have": ["MCP"],
            },
            category="",
            subcategory="",
            scope="all",
            sort="stars",
            page=1,
            limit=10,
        )
        # 显式非相关性排序时不采用宿主意图
        self.assertFalse(request.client_intent_used)
        self.assertEqual(request.effective_sort, "stars")

        relevance_request = project_discovery._normalize_search_request(
            query="MCP Python SDK",
            mode="ai",
            language="",
            client_intent={
                "language": "en",
                "intent_class": "sdk",
                "lexical_terms": ["MCP", "Python", "SDK"],
                "semantic_queries": ["MCP Python SDK examples"],
                "must_have": ["MCP"],
            },
            category="",
            subcategory="",
            scope="all",
            sort=None,
            page=1,
            limit=10,
        )
        self.assertTrue(relevance_request.client_intent_used)
        self.assertEqual(relevance_request.lexical_query, "MCP Python SDK")
        self.assertEqual(relevance_request.intent.must_have, ("MCP",))

    def test_resolve_strategy_falls_back_to_legacy(self) -> None:
        original = project_discovery.settings.project_ai_search_strategy
        try:
            for raw, expected in [("V2", "v2"), ("shadow", "shadow"), ("bogus", "legacy"), ("", "legacy")]:
                project_discovery.settings.project_ai_search_strategy = raw
                self.assertEqual(project_discovery._resolve_strategy(), expected)
        finally:
            project_discovery.settings.project_ai_search_strategy = original

    def test_github_fallback_skip_reason_priority_order(self) -> None:
        base_kwargs = {
            "query": "agent",
            "mode": "ai",
            "language": "",
            "client_intent": None,
            "category": "",
            "subcategory": "",
            "scope": "all",
            "sort": None,
            "page": 1,
            "limit": 10,
        }
        request = project_discovery._normalize_search_request(**base_kwargs)
        self.assertEqual(project_discovery._github_fallback_skip_reason(request), "")

        paged = project_discovery._normalize_search_request(
            **{**base_kwargs, "page": 2, "scope": "today", "category": "agents_automation"}
        )
        self.assertEqual(
            project_discovery._github_fallback_skip_reason(paged),
            "fallback_is_first_page_only",
        )

        scoped = project_discovery._normalize_search_request(
            **{**base_kwargs, "scope": "recommended", "category": "agents_automation"}
        )
        self.assertEqual(
            project_discovery._github_fallback_skip_reason(scoped),
            "scope_requires_local_metrics",
        )

        taxonomy = project_discovery._normalize_search_request(
            **{**base_kwargs, "subcategory": "agent_framework", "sort": "recent"}
        )
        self.assertEqual(
            project_discovery._github_fallback_skip_reason(taxonomy),
            "taxonomy_filter_requires_local_classification",
        )

        recent = project_discovery._normalize_search_request(**{**base_kwargs, "sort": "recent"})
        self.assertEqual(
            project_discovery._github_fallback_skip_reason(recent),
            "sort_not_equivalent_on_github_search",
        )

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
