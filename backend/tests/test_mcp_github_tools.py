from __future__ import annotations

import asyncio
import base64
import json
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_mcp
from backend.app.api.dependencies import (
    get_application_repositories,
    get_briefing_repository,
    get_project_search_runtime,
)
from backend.app.repositories.briefing_repository import BriefingReader
from backend.app.repositories.document_repository import (
    DocumentRepository,
)
from backend.app.services import project_discovery
from backend.app.services.ingestion import source_github_mcp
from backend.app.services.mcp.contracts import SearchGitHubAIProjectsInput, input_schema
from backend.app.services.mcp.inbound import (
    catalog as inbound_catalog,
    responses as inbound_responses,
    tools as inbound_tools,
)


class ToolMetadataTests(unittest.TestCase):
    def test_tool_names_and_routing_boundaries(self) -> None:
        tools = {tool["name"]: tool for tool in inbound_catalog.MCP_TOOLS}
        self.assertEqual(len(tools), 8)
        self.assertTrue(
            {
                "search_papers",
                "search_documents",
                "get_paper_detail",
                "get_top_items",
                "search_github_projects",
                "search_github_ai_projects",
                "get_project_library",
                "get_project_categories",
            }.issubset(tools)
        )
        generic = tools["search_github_projects"]["description"].lower()
        papers = tools["search_papers"]["description"].lower()
        ai = tools["search_github_ai_projects"]["description"].lower()
        legacy = tools["get_project_library"]["description"].lower()
        for trigger in ("find", "search", "recommend", "compare", "reuse"):
            self.assertIn(trigger, generic)
            self.assertIn(trigger, ai)
        for artifact in ("project", "sdk", "framework", "component", "template", "example", "tutorial"):
            self.assertIn(artifact, generic)
            self.assertIn(artifact, ai)
        self.assertIn("non-ai", generic)
        self.assertIn("screenshot", generic)
        self.assertIn("major non-ai module", generic)
        self.assertIn("independent subsystem", generic)
        self.assertIn("simple crud", generic)
        self.assertIn("isolated function", generic)
        self.assertIn("at most one initial search", generic)
        self.assertIn("architecture-changing adoption", generic)
        self.assertIn("search_github_ai_projects", generic)
        self.assertIn("scholarly outputs", papers)
        self.assertIn("surveys or systematic reviews", papers)
        self.assertIn("citations", papers)
        self.assertIn("academic evaluations", papers)
        self.assertIn("agent/mcp is only a topic", papers)
        self.assertIn("search_github_ai_projects first", papers)
        self.assertIn("1-3 established technical terms", papers)
        self.assertIn("dominant deliverable", papers)
        self.assertIn("native websearch/webfetch/bash", papers)
        self.assertIn("call fails", papers)
        self.assertIn("no usable or relevant items", papers)
        self.assertIn("mcp-first local search", ai)
        self.assertIn("agent", ai)
        self.assertIn("rag", ai)
        self.assertIn("major ai module", ai)
        self.assertIn("independent subsystem", ai)
        self.assertIn("improve ai development efficiency", ai)
        self.assertIn("simple crud", ai)
        self.assertIn("isolated function", ai)
        self.assertIn("at most one initial search", ai)
        self.assertIn("architecture-changing adoption", ai)
        self.assertIn("search_papers first only", ai)
        self.assertIn("dominant deliverable", ai)
        self.assertIn("default to relevance", ai)
        for tool_name in ("search_github_ai_projects", "get_project_library"):
            sort_schema = tools[tool_name]["inputSchema"]["properties"]["sort"]
            self.assertIn("relevance", json.dumps(sort_schema))
        generic_schema = input_schema("search_github_projects")
        self.assertIn("relevance", json.dumps(generic_schema["properties"]["sort"]))
        self.assertNotIn("intent", generic_schema["properties"])
        favorites_schema = input_schema("search_my_project_favorites")
        self.assertNotIn("relevance", json.dumps(favorites_schema["properties"]["sort"]))
        self.assertNotIn("intent", favorites_schema["properties"])
        for tool_name in ("search_github_ai_projects", "get_project_library"):
            self.assertIn("intent", tools[tool_name]["inputSchema"]["properties"])
        for description in (generic, ai, legacy):
            self.assertIn("500 github stars", description)
            self.assertIn("unverifiable or below-threshold", description)
        for description in (generic, ai):
            self.assertIn("do not batch", description)
            self.assertIn("websearch/webfetch/bash", description)
            self.assertIn("inspect the mcp result first", description)
            self.assertIn("call fails", description)
            self.assertIn("no usable or relevant items", description)
            self.assertIn("missing detail", description)
        self.assertIn("favorites", generic)
        self.assertIn("excludes", ai)
        self.assertIn("legacy", legacy)
        self.assertEqual(tools["search_github_projects"]["inputSchema"]["required"], ["q"])


class HostIntentContractTests(unittest.TestCase):
    def _intent(self) -> dict:
        return {
            "schema_version": "project-search-intent-client-v1",
            "language": "en",
            "intent_class": "sdk",
            "lexical_terms": ["MCP", "Python", "SDK"],
            "semantic_queries": ["MCP Python SDK server examples"],
            "must_have": ["MCP", "Python"],
        }

    def test_valid_intent_is_normalized_without_changing_top_level_filters(self) -> None:
        validated = SearchGitHubAIProjectsInput.model_validate(
            {
                "q": "MCP Python SDK",
                "category": "agents_automation",
                "language": "Python",
                "sort": "relevance",
                "intent": self._intent(),
            }
        )

        self.assertEqual(validated.category, "agents_automation")
        self.assertEqual(validated.language, "Python")
        self.assertEqual(validated.sort, "relevance")
        self.assertEqual(validated.intent.lexical_terms, ["MCP", "Python", "SDK"])

    def test_invalid_version_unknown_key_and_removed_token_are_rejected(self) -> None:
        invalid_payloads = []
        wrong_version = self._intent()
        wrong_version["schema_version"] = "v2"
        invalid_payloads.append(wrong_version)
        unknown_key = self._intent()
        unknown_key["sort"] = "stars"
        invalid_payloads.append(unknown_key)
        removed_token = self._intent()
        removed_token["lexical_terms"] = ["Python", "SDK"]
        removed_token["semantic_queries"] = ["Python SDK examples"]
        invalid_payloads.append(removed_token)

        for intent in invalid_payloads:
            with self.subTest(intent=intent):
                with self.assertRaises(Exception):
                    SearchGitHubAIProjectsInput.model_validate(
                        {"q": "MCP Python SDK", "intent": intent}
                    )

    def test_control_character_and_oversized_values_are_rejected(self) -> None:
        control = self._intent()
        control["lexical_terms"] = ["MCP\nPython"]
        oversized = self._intent()
        oversized["semantic_queries"] = ["MCP " + "x" * 121]

        for intent in (control, oversized):
            with self.subTest(intent=intent):
                with self.assertRaises(Exception):
                    SearchGitHubAIProjectsInput.model_validate(
                        {"q": "MCP Python SDK", "intent": intent}
                    )


class QueryModeTests(unittest.TestCase):
    def test_search_normalization_never_treats_watchers_count_as_subscribers(self) -> None:
        normalized = source_github_mcp._normalize_repo(
            {
                "id": 1,
                "full_name": "owner/repo",
                "stargazers_count": 700,
                "watchers_count": 700,
            }
        )

        self.assertEqual(normalized["watchers"], 0)
        self.assertFalse(normalized["community_metrics_complete"])

    def test_normalization_accepts_explicit_subscribers_count(self) -> None:
        normalized = source_github_mcp._normalize_repo(
            {
                "id": 1,
                "full_name": "owner/repo",
                "stargazers_count": 700,
                "watchers_count": 700,
                "subscribers_count": 12,
            }
        )

        self.assertEqual(normalized["watchers"], 12)
        self.assertTrue(normalized["community_metrics_complete"])

    def setUp(self) -> None:
        source_github_mcp._clear_fallback_cache()

    def test_generic_query_never_appends_ai_terms(self) -> None:
        queries = source_github_mcp._build_queries(
            q="Windows screenshot rounded corners iShot",
            category="",
            subcategory="",
            language="",
            min_stars=500,
            mode="generic",
        )
        self.assertEqual(queries[0], "Windows screenshot rounded corners iShot stars:>=500")
        self.assertTrue(all("LLM" not in query for query in queries))
        self.assertTrue(all("RAG" not in query for query in queries))
        self.assertTrue(all("agent" not in query.lower() for query in queries))

    def test_generic_long_query_adds_progressively_relaxed_retries(self) -> None:
        queries = source_github_mcp._build_queries(
            q="Windows screenshot rounded corners iShot",
            category="",
            subcategory="",
            language="",
            min_stars=500,
            mode="generic",
        )
        self.assertEqual(
            queries,
            [
                "Windows screenshot rounded corners iShot stars:>=500",
                "Windows screenshot rounded corners stars:>=500",
                "Windows screenshot stars:>=500",
            ],
        )
        self.assertTrue(all("LLM" not in query and "RAG" not in query for query in queries))

    def test_generic_query_keeps_user_supplied_ai_term(self) -> None:
        queries = source_github_mcp._build_queries(
            q="local RAG desktop app",
            category="",
            subcategory="",
            language="Python",
            min_stars=500,
            mode="generic",
        )
        self.assertIn("RAG", queries[0])
        self.assertIn("language:Python", queries[0])

    def test_ai_mode_retains_ai_retry(self) -> None:
        queries = source_github_mcp._build_queries(
            q="local knowledge base",
            category="rag_knowledge",
            subcategory="",
            language="",
            min_stars=500,
            mode="ai",
        )
        self.assertGreaterEqual(len(queries), 1)
        self.assertTrue(any(term in " ".join(queries).lower() for term in ("rag", "llm", "ai")))

    def test_fallback_cache_returns_defensive_copy(self) -> None:
        fake = {
            "items": [{"id": 1, "full_name": "owner/repo", "html_url": "https://github.com/owner/repo", "stargazers_count": 500}],
            "total_count": 1,
            "error": "",
        }
        with patch.object(source_github_mcp, "_search_once", return_value=fake) as search_once:
            first = source_github_mcp.search_github_projects_fallback(q="rounded screenshot", limit=3)
            first["items"][0]["full_name"] = "mutated"
            second = source_github_mcp.search_github_projects_fallback(q="rounded screenshot", limit=3)
        self.assertEqual(search_once.call_count, 1)
        self.assertFalse(first["cache_hit"])
        self.assertTrue(second["cache_hit"])
        self.assertEqual(second["items"][0]["full_name"], "owner/repo")

    def test_fallback_stops_relaxed_retries_after_limit_is_filled(self) -> None:
        empty = {"items": [], "total_count": 0, "error": ""}
        match = {
            "items": [{"id": 1, "full_name": "owner/repo", "html_url": "https://github.com/owner/repo", "stargazers_count": 500}],
            "total_count": 1,
            "error": "",
        }
        with patch.object(source_github_mcp, "_search_once", side_effect=[empty, match, empty]) as search_once:
            result = source_github_mcp.search_github_projects_fallback(
                q="Windows screenshot rounded corners iShot",
                limit=1,
            )
        self.assertEqual(search_once.call_count, 3)
        self.assertEqual(result["items"][0]["full_name"], "owner/repo")
        self.assertEqual(len(result["queries"]), 3)

    def test_fallback_globally_sorts_across_retries(self) -> None:
        low = {
            "items": [
                {"id": 1, "full_name": "owner/boundary", "stargazers_count": 500},
                {"id": 3, "full_name": "owner/rejected", "stargazers_count": 499},
            ],
            "total_count": 2,
            "error": "",
        }
        high = {
            "items": [{"id": 2, "full_name": "owner/high", "stargazers_count": 10000}],
            "total_count": 1,
            "error": "",
        }
        empty = {"items": [], "total_count": 0, "error": ""}
        with patch.object(source_github_mcp, "_search_once", side_effect=[low, high, empty]):
            result = source_github_mcp.search_github_projects_fallback(
                q="Windows screenshot rounded corners iShot",
                sort="stars",
                limit=2,
            )
        self.assertEqual(
            [item["full_name"] for item in result["items"]],
            ["owner/high", "owner/boundary"],
        )

    def test_fallback_rejects_malformed_and_below_threshold_stars(self) -> None:
        invalid_values = (None, "500", 500.0, True, 499)
        items = [
            {"id": index, "full_name": f"owner/invalid-{index}", "stargazers_count": value}
            for index, value in enumerate(invalid_values, start=1)
        ]
        items.append({"id": 99, "full_name": "owner/missing"})
        items.append({"id": 100, "full_name": "owner/boundary", "stargazers_count": 500})
        fake = {"items": items, "total_count": len(items), "error": ""}

        with patch.object(source_github_mcp, "_search_once", return_value=fake):
            result = source_github_mcp.search_github_projects_fallback(
                q="rounded screenshot",
                min_stars=50,
            )
            cached = source_github_mcp.search_github_projects_fallback(
                q="rounded screenshot",
                min_stars=50,
            )

        self.assertEqual(result["queries"][0], "rounded screenshot stars:>=500")
        self.assertEqual([item["full_name"] for item in result["items"]], ["owner/boundary"])
        self.assertTrue(cached["cache_hit"])
        self.assertEqual([item["full_name"] for item in cached["items"]], ["owner/boundary"])

    def test_fallback_cache_evicts_oldest_entry(self) -> None:
        fake = {"items": [], "total_count": 0, "error": ""}
        with (
            patch.object(source_github_mcp, "_CACHE_MAX_ENTRIES", 2),
            patch.object(source_github_mcp, "_search_once", return_value=fake),
        ):
            source_github_mcp.search_github_projects_fallback(q="one")
            source_github_mcp.search_github_projects_fallback(q="two")
            source_github_mcp.search_github_projects_fallback(q="three")
        cached_queries = [key[1] for key in source_github_mcp._FALLBACK_CACHE]
        self.assertEqual(cached_queries, ["two", "three"])

    def test_ai_compatibility_wrapper_uses_ai_mode(self) -> None:
        with patch.object(source_github_mcp, "search_github_projects_fallback", return_value={}) as fallback:
            source_github_mcp.search_github_ai_projects_fallback(q="RAG")
        self.assertEqual(fallback.call_args.kwargs["mode"], "ai")
        self.assertEqual(fallback.call_args.kwargs["min_stars"], 500)


class ProjectHandlerTests(unittest.TestCase):
    def _repository(self, result: dict) -> MagicMock:
        repository = MagicMock()
        repository.list_projects.return_value = result
        return repository

    def test_generic_miss_uses_generic_fallback(self) -> None:
        fallback_result = {
            "items": [{"id": "x", "full_name": "owner/repo", "url": "https://github.com/owner/repo", "stars": 500}],
            "total": 1,
            "github_total_count": 1,
            "queries": ["screenshot rounded stars:>=500"],
            "error": "",
            "cache_hit": False,
        }
        with (
            patch.object(project_discovery, "get_project_catalog_repository", return_value=self._repository({"items": [], "total": 0})),
            patch.object(project_discovery.settings, "project_semantic_search_enabled", False),
            patch.object(inbound_tools, "search_github_projects_fallback", return_value=fallback_result) as fallback,
        ):
            result = asyncio.run(inbound_tools._search_project_library({"q": "screenshot rounded"}, mode="generic"))
        self.assertEqual(fallback.call_args.kwargs["mode"], "generic")
        self.assertEqual(fallback.call_args.kwargs["min_stars"], 500)
        self.assertEqual(result["result_origin"], "github_api_fallback")
        self.assertEqual(result["items"][0]["full_name"], "owner/repo")

    def test_ai_alias_miss_uses_ai_fallback(self) -> None:
        with (
            patch.object(project_discovery, "get_project_catalog_repository", return_value=self._repository({"items": [], "total": 0})),
            patch.object(
                inbound_tools,
                "search_github_projects_fallback",
                return_value={"items": [], "total": 0, "github_total_count": 0, "queries": [], "error": "", "cache_hit": False},
            ) as fallback,
        ):
            asyncio.run(inbound_tools._tool_search_github_ai_projects(None, {"q": "RAG", "sort": "stars"}))
        self.assertEqual(fallback.call_args.kwargs["mode"], "ai")
        self.assertEqual(fallback.call_args.kwargs["min_stars"], 500)

    def test_ai_handler_forwards_host_intent(self) -> None:
        intent = HostIntentContractTests()._intent()
        with patch.object(
            inbound_tools, "search_projects", new=AsyncMock(return_value={})
        ) as search:
            asyncio.run(
                inbound_tools._tool_search_github_ai_projects(
                    None, {"q": "MCP Python SDK", "intent": intent}
                )
            )
        self.assertEqual(search.call_args.kwargs["client_intent"], intent)
        self.assertEqual(search.call_args.kwargs["query"], "MCP Python SDK")

    def test_local_hit_suppresses_fallback(self) -> None:
        local = {"items": [{"id": "x", "full_name": "owner/local", "stars": 900}], "total": 1}
        with (
            patch.object(project_discovery, "get_project_catalog_repository", return_value=self._repository(local)),
            patch.object(inbound_tools, "search_github_projects_fallback") as fallback,
        ):
            result = asyncio.run(inbound_tools._search_project_library({"q": "local"}, mode="generic"))
        fallback.assert_not_called()
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["items"][0]["result_origin"], "aigc_news_local")

    def test_today_miss_does_not_fallback(self) -> None:
        with (
            patch.object(project_discovery, "get_project_catalog_repository", return_value=self._repository({"items": [], "total": 0})),
            patch.object(inbound_tools, "search_github_projects_fallback") as fallback,
        ):
            result = asyncio.run(inbound_tools._search_project_library({"scope": "today"}, mode="ai"))
        fallback.assert_not_called()
        self.assertFalse(result["fallback_used"])

    def test_project_projection_is_compact(self) -> None:
        projected = project_discovery.public_project_item(
            {
                "id": "x",
                "full_name": "owner/repo",
                "description": "d" * 1000,
                "description_zh": "中" * 500,
                "tags": [f"tag-{i}" for i in range(20)],
                "topics": [f"topic-{i}" for i in range(20)],
                "stars": 42,
                "is_favorited": True,
                "hot_score_growth": 99,
            }
        )
        self.assertLessEqual(len(projected["description"]), 320)
        self.assertLessEqual(len(projected["description_zh"]), 160)
        self.assertEqual(len(projected["tags"]), 4)
        self.assertEqual(len(projected["topics"]), 4)
        self.assertNotIn("is_favorited", projected)
        self.assertNotIn("hot_score_growth", projected)

    def test_worst_case_project_response_stays_under_tool_limit(self) -> None:
        item = project_discovery.public_project_item(
            {
                "id": "github-direct:owner/repository-name",
                "full_name": "owner/repository-name",
                "url": "https://github.com/owner/repository-name",
                "description": "d" * 1000,
                "description_zh": "中" * 500,
                "category_slug": "productivity",
                "category_name": "Productivity",
                "subcategory_slug": "screenshots",
                "subcategory_name": "Screenshots",
                "tags": ["tag" * 30] * 10,
                "topics": ["topic" * 30] * 10,
                "language": "C#",
                "stars": 999999,
                "forks": 99999,
                "pushed_at": "2026-07-10T00:00:00Z",
                "daily_star_growth": 999,
                "daily_growth_available": True,
                "hot_score": 123.456,
                "is_recommended": True,
            }
        )
        tool_result = inbound_responses._tool_response({"items": [item for _ in range(20)], "total": 20})
        envelope = {"jsonrpc": "2.0", "id": 1, "result": tool_result}
        encoded = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        self.assertLess(len(encoded), inbound_responses.MAX_TOOL_RESULT_CHARS)
        self.assertNotIn('"truncated": true', encoded.decode("utf-8"))


class McpProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        self.briefing_repository = MagicMock(spec=BriefingReader)
        self.papers_repository = MagicMock(spec=DocumentRepository)
        self.application_repositories = types.SimpleNamespace(
            documents=self.papers_repository,
            rank_snapshots=MagicMock(),
            project_collections=MagicMock(),
        )
        self.project_search_runtime = types.SimpleNamespace(
            search_projects=project_discovery.search_projects,
        )
        app.dependency_overrides[get_briefing_repository] = (
            lambda: self.briefing_repository
        )
        app.dependency_overrides[get_application_repositories] = (
            lambda: self.application_repositories
        )
        app.dependency_overrides[get_project_search_runtime] = (
            lambda: self.project_search_runtime
        )
        app.include_router(routes_mcp.router, prefix="/api")
        self.client = TestClient(app)

    def test_paper_detail_tool_uses_injected_papers_reader(self) -> None:
        self.papers_repository.get_paper_detail.return_value = {
            "id": "paper-1",
            "source": "arxiv",
            "title": "Paper",
            "local_pdf_path": "/srv/papers/paper-1.pdf",
        }

        response = self.client.post(
            "/api/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "get_paper_detail",
                    "arguments": {"paper_id": "paper-1"},
                },
            },
        )

        self.papers_repository.get_paper_detail.assert_called_once_with("paper-1")
        item = response.json()["result"]["structuredContent"]["item"]
        self.assertEqual(item["id"], "paper-1")
        self.assertNotIn("local_pdf_path", item)
        self.assertTrue(item["pdf_media_url"].endswith("/api/media/papers/paper-1.pdf"))

    def test_paper_detail_resource_uses_injected_papers_reader(self) -> None:
        self.papers_repository.get_paper_detail.return_value = {
            "id": "paper-2",
            "source": "arxiv",
            "title": "Resource Paper",
        }

        response = self.client.post(
            "/api/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "resources/read",
                "params": {"uri": "aigc-news://papers/paper-2"},
            },
        )

        self.papers_repository.get_paper_detail.assert_called_once_with("paper-2")
        content = json.loads(response.json()["result"]["contents"][0]["text"])
        self.assertEqual(content["item"]["title"], "Resource Paper")

    def test_latest_report_resource_uses_injected_repository(self) -> None:
        self.briefing_repository.get_briefing_by_date.return_value = {
            "content": "# Cached briefing"
        }

        response = self.client.post(
            "/api/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "resources/read",
                "params": {
                    "uri": (
                        "aigc-news://report/latest"
                        "?source=github&period=weekly&date=2026-07-22"
                    )
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        self.briefing_repository.get_briefing_by_date.assert_called_once_with(
            "2026-07-20_github_weekly"
        )
        content = response.json()["result"]["contents"][0]
        self.assertEqual(content["mimeType"], "text/markdown")
        self.assertEqual(content["text"], "# Cached briefing")

    def test_missing_latest_report_preserves_jsonrpc_error(self) -> None:
        self.briefing_repository.get_briefing_by_date.return_value = None

        response = self.client.post(
            "/api/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "resources/read",
                "params": {"uri": "aigc-news://report/latest?date=2026-07-22"},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["error"]["code"], -32602)
        self.assertIn("2026-07-22_daily", response.json()["error"]["message"])

    def test_initialize_and_tools_list(self) -> None:
        initialized = self.client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        self.assertEqual(initialized.status_code, 200)
        initialize_result = initialized.json()["result"]
        self.assertEqual(initialize_result["protocolVersion"], inbound_catalog.MCP_PROTOCOL_VERSION)
        self.assertEqual(initialize_result["serverInfo"]["name"], inbound_catalog.MCP_SERVER_NAME)
        self.assertIn("tools", initialize_result["capabilities"])
        instructions = initialize_result["instructions"].lower()
        for trigger in ("find", "search", "recommend", "compare", "reuse"):
            self.assertIn(trigger, instructions)
        self.assertIn("search_github_ai_projects", instructions)
        self.assertIn("search_github_projects", instructions)
        self.assertIn("search_papers", instructions)
        self.assertIn("major module", instructions)
        self.assertIn("independent subsystem", instructions)
        self.assertIn("improve ai development efficiency", instructions)
        self.assertIn("simple crud", instructions)
        self.assertIn("isolated function", instructions)
        self.assertIn("at most one initial search", instructions)
        self.assertIn("do not batch", instructions)
        self.assertIn("finding a candidate does not authorize adoption", instructions)
        self.assertIn("await the user's choice", instructions)
        self.assertIn("500 github stars", instructions)
        self.assertIn("unverifiable or below 500", instructions)
        self.assertIn("cannot override a client's system prompt", instructions)
        self.assertTrue(initialized.headers.get("mcp-session-id"))
        notification = self.client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        self.assertEqual(notification.status_code, 204)
        listed = self.client.post(
            "/api/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        self.assertEqual(len(listed.json()["result"]["tools"]), 8)

    def test_prompts_require_mcp_first_and_sequential_web_fallback(self) -> None:
        prompts = {}
        for request_id, name in ((3, "daily_research_brief"), (4, "project_discovery")):
            response = self.client.post(
                "/api/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "prompts/get",
                    "params": {"name": name, "arguments": {}},
                },
            )
            self.assertEqual(response.status_code, 200)
            prompts[name] = response.json()["result"]["messages"][0]["content"]["text"].lower()

        research = prompts["daily_research_brief"]
        for trigger in ("find", "search", "recommend", "compare", "reuse"):
            self.assertIn(trigger, research)
        self.assertIn("search_github_ai_projects`", research)
        self.assertIn("search_github_projects`", research)
        self.assertIn("search_papers` first only", research)
        self.assertIn("explicitly scholarly", research)
        self.assertIn("major module", research)
        self.assertIn("independent subsystem", research)
        self.assertIn("improve ai development efficiency", research)
        self.assertIn("simple crud", research)
        self.assertIn("isolated function", research)
        self.assertIn("at most one initial search", research)
        self.assertIn("dominant deliverable", research)
        self.assertIn("do not batch primary searches", research)
        self.assertIn("design-reference", research)
        self.assertIn("await the user's choice", research)
        self.assertIn("await and inspect the selected aigc_news result", research)
        self.assertIn("call fails", research)
        self.assertIn("missing detail", research)
        self.assertIn("500 github stars", research)
        self.assertIn("unverifiable or below-threshold", research)

        projects = prompts["project_discovery"]
        for trigger in ("find", "search", "recommend", "compare", "reuse"):
            self.assertIn(trigger, projects)
        for artifact in ("project", "repository", "sdk", "framework", "component", "template", "example", "tutorial"):
            self.assertIn(artifact, projects)
        self.assertIn("search_github_ai_projects` first", projects)
        self.assertIn("search_github_projects` first", projects)
        self.assertIn("search_papers` first only", projects)
        self.assertIn("dominant deliverable", projects)
        self.assertIn("major module", projects)
        self.assertIn("independent subsystem", projects)
        self.assertIn("improve ai development efficiency", projects)
        self.assertIn("auth/permissions", projects)
        self.assertIn("simple crud", projects)
        self.assertIn("isolated function", projects)
        self.assertIn("do not put the selected mcp search", projects)
        self.assertIn("same initial tool batch", projects)
        self.assertIn("await and inspect the mcp result first", projects)
        self.assertIn("call fails", projects)
        self.assertIn("no usable or relevant items", projects)
        self.assertIn("missing detail", projects)
        self.assertIn("500 github stars", projects)
        self.assertIn("unverifiable or below 500", projects)
        self.assertIn("at most one initial search per unchanged requirement", projects)
        self.assertIn("use it only as a design reference", projects)
        self.assertIn("do not start implementation in the same turn", projects)
        self.assertIn("cannot override a client's own system prompt", projects)

    def test_search_papers_uses_shared_repository_and_hides_local_path(self) -> None:
        repository = self.papers_repository
        repository.search_document_page.return_value = {
            "items": [
                {
                    "id": "paper-1",
                    "source": "arxiv",
                    "title": "Agent Paper",
                    "local_pdf_path": "/tmp/agent.pdf",
                }
            ],
            "total": 1,
        }
        response = self.client.post(
            "/api/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "search_papers",
                    "arguments": {"q": "  Agent  ", "limit": 20},
                },
            },
        )

        repository.search_document_page.assert_called_once_with(
            "Agent", source="arxiv", page=1, page_size=20
        )
        payload = response.json()["result"]["structuredContent"]
        self.assertEqual(payload["q"], "Agent")
        self.assertEqual(payload["total"], 1)
        self.assertNotIn("local_pdf_path", payload["items"][0])
        self.assertTrue(payload["items"][0]["pdf_media_url"].endswith("/api/media/papers/agent.pdf"))

    def test_authenticated_token_adds_private_favorites_tool(self) -> None:
        async def authenticated_user():
            return {"user_id": 42, "role": "user", "scopes": frozenset({"projects:favorites:read"})}

        self.client.app.dependency_overrides[routes_mcp.OptionalMcpUser] = authenticated_user
        try:
            listed = self.client.post(
                "/api/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            )
        finally:
            self.client.app.dependency_overrides.clear()
        names = {tool["name"] for tool in listed.json()["result"]["tools"]}
        self.assertEqual(len(names), 9)
        self.assertIn("search_my_project_favorites", names)

    def test_private_favorites_tool_is_owner_scoped(self) -> None:
        async def authenticated_user():
            return {"user_id": 42, "role": "user", "scopes": frozenset({"projects:favorites:read"})}

        repository = MagicMock()
        repository.list_user_project_collection.return_value = {
            "items": [{"id": "github:1", "full_name": "owner/private", "stars": 900}],
            "total": 1,
        }
        self.client.app.dependency_overrides[routes_mcp.OptionalMcpUser] = authenticated_user
        try:
            with patch.object(
                self.application_repositories,
                "project_collections",
                repository,
            ):
                response = self.client.post(
                    "/api/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "search_my_project_favorites", "arguments": {"q": "private"}},
                    },
                )
        finally:
            self.client.app.dependency_overrides.clear()
        self.assertFalse(response.json()["result"]["isError"])
        self.assertEqual(repository.list_user_project_collection.call_args.kwargs["user_id"], 42)
        self.assertEqual(repository.list_user_project_collection.call_args.kwargs["source"], "github")

    def test_private_favorites_tool_forwards_tag_and_opaque_marker(self) -> None:
        async def authenticated_user():
            return {"user_id": 42, "scopes": frozenset({"projects:favorites:read"})}

        repository = MagicMock()
        repository.list_user_project_collection.side_effect = [
            {"items": [{"id": "github:1", "full_name": "owner/first"}] * 10, "total": 25},
            {"items": [{"id": "github:2", "full_name": "owner/tagged"}], "total": 25},
        ]
        self.client.app.dependency_overrides[routes_mcp.OptionalMcpUser] = authenticated_user
        try:
            with patch.object(
                self.application_repositories,
                "project_collections",
                repository,
            ):
                first = self.client.post(
                    "/api/mcp",
                    json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_my_project_favorites", "arguments": {"tag": "agent", "limit": 10}}},
                ).json()["result"]["structuredContent"]
                response = self.client.post(
                    "/api/mcp",
                    json={
                        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
                        "params": {"name": "search_my_project_favorites", "arguments": {"tag": "agent", "limit": 10, "marker": first["marker"]}},
                    },
                )
        finally:
            self.client.app.dependency_overrides.clear()
        payload = response.json()["result"]["structuredContent"]
        self.assertEqual(repository.list_user_project_collection.call_args.kwargs["tag"], "agent")
        self.assertEqual(repository.list_user_project_collection.call_args.kwargs["page"], 2)
        self.assertIsNotNone(payload["marker"])

    def test_private_favorites_marker_rejects_changed_limit(self) -> None:
        async def authenticated_user():
            return {"user_id": 42, "scopes": frozenset({"projects:favorites:read"})}

        marker = base64.urlsafe_b64encode(b'{"offset":10,"limit":10}').decode().rstrip("=")
        self.client.app.dependency_overrides[routes_mcp.OptionalMcpUser] = authenticated_user
        try:
            response = self.client.post(
                "/api/mcp",
                json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "search_my_project_favorites", "arguments": {"limit": 5, "marker": marker}}},
            )
        finally:
            self.client.app.dependency_overrides.clear()
        self.assertTrue(response.json()["result"]["isError"])
        self.assertIn("different limit", response.json()["result"]["content"][0]["text"])

    def test_private_favorites_tool_requires_scope(self) -> None:
        async def authenticated_user():
            return {"user_id": 42, "scopes": frozenset()}

        self.client.app.dependency_overrides[routes_mcp.OptionalMcpUser] = authenticated_user
        try:
            response = self.client.post(
                "/api/mcp",
                json={"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "search_my_project_favorites", "arguments": {}}},
            )
        finally:
            self.client.app.dependency_overrides.clear()
        self.assertTrue(response.json()["result"]["isError"])
        self.assertIn("projects:favorites:read", response.json()["result"]["content"][0]["text"])

    def test_anonymous_private_tool_call_is_rejected(self) -> None:
        response = self.client.post(
            "/api/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "search_my_project_favorites", "arguments": {}},
            },
        )
        self.assertTrue(response.json()["result"]["isError"])
        self.assertIn("Authentication", response.json()["result"]["content"][0]["text"])

    def test_project_tools_call_through_json_rpc_surface(self) -> None:
        compact = {"items": [], "total": 0, "fallback_used": False}
        generic_handler = AsyncMock(return_value=compact)
        ai_handler = AsyncMock(return_value=compact)
        legacy_handler = AsyncMock(return_value=compact)
        handlers = dict(inbound_tools._TOOL_HANDLERS)
        inbound_tools._TOOL_HANDLERS.update(
            {
                "search_github_projects": generic_handler,
                "search_github_ai_projects": ai_handler,
                "get_project_library": legacy_handler,
            }
        )
        try:
            responses = [
                self.client.post(
                    "/api/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {"name": name, "arguments": arguments},
                    },
                )
                for request_id, name, arguments in (
                    (3, "search_github_projects", {"q": "screenshot"}),
                    (4, "search_github_ai_projects", {"q": "RAG"}),
                    (5, "get_project_library", {}),
                )
            ]
        finally:
            inbound_tools._TOOL_HANDLERS.clear()
            inbound_tools._TOOL_HANDLERS.update(handlers)
        self.assertTrue(all(not response.json()["result"]["isError"] for response in responses))
        generic_handler.assert_awaited_once()
        ai_handler.assert_awaited_once()
        legacy_handler.assert_awaited_once()

    def test_generic_fallback_provenance_and_cache_reuse_through_json_rpc(self) -> None:
        repository = MagicMock()
        repository.list_projects.return_value = {"items": [], "total": 0}
        github_items = [
            {
                "id": 1,
                "full_name": "owner/screenshot-tool",
                "html_url": "https://github.com/owner/screenshot-tool",
                "description": "Windows screenshot utility",
                "stargazers_count": 500,
            },
            {
                "id": 2,
                "full_name": "owner/below-threshold",
                "html_url": "https://github.com/owner/below-threshold",
                "stargazers_count": 499,
            },
            {
                "id": 3,
                "full_name": "owner/malformed-stars",
                "html_url": "https://github.com/owner/malformed-stars",
                "stargazers_count": "900",
            },
        ]
        source_github_mcp._clear_fallback_cache()
        with (
            patch.object(project_discovery, "get_project_catalog_repository", return_value=repository),
            patch.object(project_discovery.settings, "project_semantic_search_enabled", False),
            patch.object(source_github_mcp, "_search_once", return_value={"items": github_items, "total_count": 3, "error": ""}) as search_once,
        ):
            responses = [
                self.client.post(
                    "/api/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {"name": "search_github_projects", "arguments": {"q": "Windows screenshot"}},
                    },
                )
                for request_id in (6, 7)
            ]
        payloads = [response.json()["result"]["structuredContent"] for response in responses]
        self.assertEqual(search_once.call_count, 1)
        self.assertTrue(all(payload["result_origin"] == "github_api_fallback" for payload in payloads))
        self.assertTrue(all(payload["fallback_used"] for payload in payloads))
        self.assertFalse(payloads[0]["fallback_cache_hit"])
        self.assertTrue(payloads[1]["fallback_cache_hit"])
        self.assertEqual(
            [[item["full_name"] for item in payload["items"]] for payload in payloads],
            [["owner/screenshot-tool"], ["owner/screenshot-tool"]],
        )

    def test_generic_query_is_required(self) -> None:
        response = self.client.post(
            "/api/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "search_github_projects", "arguments": {}},
            },
        )
        result = response.json()["result"]
        self.assertTrue(result["isError"])
        self.assertIn("q", result["content"][0]["text"])

    def test_tool_schema_rejects_unknown_and_non_strict_limit(self) -> None:
        for request_id, arguments in (
            (20, {"q": "Agent", "unexpected": True}),
            (21, {"q": "Agent", "limit": "10"}),
            (22, {"q": "Agent", "limit": True}),
            (23, {"q": "Agent", "limit": 21}),
        ):
            with self.subTest(arguments=arguments):
                response = self.client.post(
                    "/api/mcp",
                    json={
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "method": "tools/call",
                        "params": {"name": "search_papers", "arguments": arguments},
                    },
                )
                self.assertTrue(response.json()["result"]["isError"])

    def test_falsey_non_object_params_are_invalid(self) -> None:
        for params in (None, False, "", 0, []):
            with self.subTest(params=params):
                response = self.client.post(
                    "/api/mcp",
                    json={"jsonrpc": "2.0", "id": 30, "method": "tools/list", "params": params},
                )
                self.assertEqual(response.json()["error"]["code"], -32602)

    def test_invalid_calendar_date_is_rejected(self) -> None:
        response = self.client.post(
            "/api/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 31,
                "method": "tools/call",
                "params": {"name": "get_top_items", "arguments": {"date": "2026-02-30"}},
            },
        )
        self.assertTrue(response.json()["result"]["isError"])

    def test_search_documents_keeps_all_source_semantics(self) -> None:
        repository = self.papers_repository
        repository.search_document_page.return_value = {"items": [], "total": 0}
        response = self.client.post(
            "/api/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 32,
                "method": "tools/call",
                "params": {"name": "search_documents", "arguments": {"q": "inference news"}},
            },
        )
        self.assertFalse(response.json()["result"]["isError"])
        repository.search_document_page.assert_called_once_with(
            "inference news", source=None, page=1, page_size=10
        )


if __name__ == "__main__":
    unittest.main()
