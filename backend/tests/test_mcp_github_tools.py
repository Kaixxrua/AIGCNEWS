from __future__ import annotations

import asyncio
import base64
import json
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

if "fastapi_cache.decorator" not in sys.modules:
    fastapi_cache = types.ModuleType("fastapi_cache")
    fastapi_cache_decorator = types.ModuleType("fastapi_cache.decorator")

    def _cache(*_args, **_kwargs):
        return lambda function: function

    fastapi_cache_decorator.cache = _cache
    sys.modules.setdefault("fastapi_cache", fastapi_cache)
    sys.modules.setdefault("fastapi_cache.decorator", fastapi_cache_decorator)

if "backend.app.repositories.mysql_repo" not in sys.modules:
    repository_module = types.ModuleType("backend.app.repositories.mysql_repo")

    class _RepositoryPlaceholder:
        pass

    repository_module.MySQLRepository = _RepositoryPlaceholder
    sys.modules["backend.app.repositories.mysql_repo"] = repository_module

if "backend.app.core.config" not in sys.modules:
    config_module = types.ModuleType("backend.app.core.config")
    config_module.settings = types.SimpleNamespace(
        mcp_github_fallback_enabled=True,
        mcp_github_fallback_use_token=False,
        mcp_github_fallback_timeout_seconds=8.0,
        project_semantic_search_enabled=False,
        project_semantic_query_timeout_seconds=1.5,
        github_token="",
        ACCESS_TOKEN_EXPIRE_MINUTES=60,
        JWT_SECRET_KEY="test-secret",
        JWT_ALGORITHM="HS256",
        SMTP_HOST="",
        SMTP_PORT=587,
        SMTP_USERNAME="",
        SMTP_PASSWORD="",
        SMTP_FROM_EMAIL="",
        SMTP_FROM_NAME="",
        SMTP_USE_TLS=True,
    )
    sys.modules["backend.app.core.config"] = config_module

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_mcp
from backend.app.api.dependencies import get_briefing_repository
from backend.app.repositories.briefing_repository import BriefingReader
from backend.app.services.ingestion import source_github_mcp


class ToolMetadataTests(unittest.TestCase):
    def test_tool_names_and_routing_boundaries(self) -> None:
        tools = {tool["name"]: tool for tool in routes_mcp.MCP_TOOLS}
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
        self.assertIn("when search is warranted", generic)
        self.assertIn("non-ai", generic)
        self.assertIn("screenshot", generic)
        self.assertIn("explicitly scholarly", papers)
        self.assertIn("surveys or systematic reviews", papers)
        self.assertIn("citations", papers)
        self.assertIn("benchmarks or evaluations", papers)
        self.assertIn("agent/mcp is only a topic", papers)
        self.assertIn("generic agent/mcp learning", papers)
        self.assertIn("search_github_ai_projects first", papers)
        self.assertIn("1-3 established technical terms", papers)
        self.assertIn("dominant deliverable", papers)
        self.assertIn("do not batch both primary searches", papers)
        self.assertIn("native websearch/webfetch", papers)
        self.assertIn("call fails", papers)
        self.assertIn("no relevant items", papers)
        self.assertIn("default first search for agent/mcp topics", ai)
        self.assertIn("generic learning resources", ai)
        self.assertIn("tutorials", ai)
        self.assertIn("sdks", ai)
        self.assertIn("tool calling", ai)
        self.assertIn("search_papers first only", ai)
        self.assertIn("dominant deliverable", ai)
        self.assertIn("search_github_projects", ai)
        for description in (generic, ai):
            self.assertIn("do not batch", description)
            self.assertIn("websearch/webfetch/bash", description)
            self.assertIn("inspect the mcp result first", description)
            self.assertIn("call fails", description)
            self.assertIn("no usable items", description)
            self.assertIn("missing detail", description)
        self.assertIn("favorites", generic)
        self.assertIn("do not call", generic)
        self.assertIn("complete product", generic)
        self.assertIn("excludes", ai)
        self.assertIn("narrow edits", ai)
        self.assertIn("legacy", legacy)
        self.assertEqual(tools["search_github_projects"]["inputSchema"]["required"], ["q"])


class QueryModeTests(unittest.TestCase):
    def setUp(self) -> None:
        source_github_mcp._clear_fallback_cache()

    def test_generic_query_never_appends_ai_terms(self) -> None:
        queries = source_github_mcp._build_queries(
            q="Windows screenshot rounded corners iShot",
            category="",
            subcategory="",
            language="",
            min_stars=50,
            mode="generic",
        )
        self.assertEqual(queries[0], "Windows screenshot rounded corners iShot stars:>=50")
        self.assertTrue(all("LLM" not in query for query in queries))
        self.assertTrue(all("RAG" not in query for query in queries))
        self.assertTrue(all("agent" not in query.lower() for query in queries))

    def test_generic_long_query_adds_progressively_relaxed_retries(self) -> None:
        queries = source_github_mcp._build_queries(
            q="Windows screenshot rounded corners iShot",
            category="",
            subcategory="",
            language="",
            min_stars=50,
            mode="generic",
        )
        self.assertEqual(
            queries,
            [
                "Windows screenshot rounded corners iShot stars:>=50",
                "Windows screenshot rounded corners stars:>=50",
                "Windows screenshot stars:>=50",
            ],
        )
        self.assertTrue(all("LLM" not in query and "RAG" not in query for query in queries))

    def test_generic_query_keeps_user_supplied_ai_term(self) -> None:
        queries = source_github_mcp._build_queries(
            q="local RAG desktop app",
            category="",
            subcategory="",
            language="Python",
            min_stars=50,
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
            "items": [{"id": 1, "full_name": "owner/repo", "html_url": "https://github.com/owner/repo"}],
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
            "items": [{"id": 1, "full_name": "owner/repo", "html_url": "https://github.com/owner/repo"}],
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
            "items": [{"id": 1, "full_name": "owner/low", "stargazers_count": 10}],
            "total_count": 1,
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
            ["owner/high", "owner/low"],
        )

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
            "items": [{"id": "x", "full_name": "owner/repo", "url": "https://github.com/owner/repo", "stars": 100}],
            "total": 1,
            "github_total_count": 1,
            "queries": ["screenshot rounded stars:>=50"],
            "error": "",
            "cache_hit": False,
        }
        with (
            patch.object(routes_mcp, "MySQLRepository", return_value=self._repository({"items": [], "total": 0})),
            patch.object(routes_mcp, "search_github_projects_fallback", return_value=fallback_result) as fallback,
        ):
            result = asyncio.run(routes_mcp._search_project_library({"q": "screenshot rounded"}, mode="generic"))
        self.assertEqual(fallback.call_args.kwargs["mode"], "generic")
        self.assertEqual(fallback.call_args.kwargs["min_stars"], 50)
        self.assertEqual(result["result_origin"], "github_api_fallback")
        self.assertEqual(result["items"][0]["full_name"], "owner/repo")

    def test_ai_alias_miss_uses_ai_fallback(self) -> None:
        with (
            patch.object(routes_mcp, "MySQLRepository", return_value=self._repository({"items": [], "total": 0})),
            patch.object(
                routes_mcp,
                "search_github_projects_fallback",
                return_value={"items": [], "total": 0, "github_total_count": 0, "queries": [], "error": "", "cache_hit": False},
            ) as fallback,
        ):
            asyncio.run(routes_mcp._tool_search_github_ai_projects(None, {"q": "RAG"}))
        self.assertEqual(fallback.call_args.kwargs["mode"], "ai")
        self.assertEqual(fallback.call_args.kwargs["min_stars"], 500)

    def test_local_hit_suppresses_fallback(self) -> None:
        local = {"items": [{"id": "x", "full_name": "owner/local", "stars": 900}], "total": 1}
        with (
            patch.object(routes_mcp, "MySQLRepository", return_value=self._repository(local)),
            patch.object(routes_mcp, "search_github_projects_fallback") as fallback,
        ):
            result = asyncio.run(routes_mcp._search_project_library({"q": "local"}, mode="generic"))
        fallback.assert_not_called()
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["items"][0]["result_origin"], "aigc_news_local")

    def test_today_miss_does_not_fallback(self) -> None:
        with (
            patch.object(routes_mcp, "MySQLRepository", return_value=self._repository({"items": [], "total": 0})),
            patch.object(routes_mcp, "search_github_projects_fallback") as fallback,
        ):
            result = asyncio.run(routes_mcp._search_project_library({"scope": "today"}, mode="ai"))
        fallback.assert_not_called()
        self.assertFalse(result["fallback_used"])

    def test_project_projection_is_compact(self) -> None:
        projected = routes_mcp._public_project_item(
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
        self.assertLessEqual(len(projected["description"]), 180)
        self.assertLessEqual(len(projected["description_zh"]), 80)
        self.assertEqual(len(projected["tags"]), 4)
        self.assertEqual(len(projected["topics"]), 4)
        self.assertNotIn("is_favorited", projected)
        self.assertNotIn("hot_score_growth", projected)

    def test_worst_case_project_response_stays_under_48_kib(self) -> None:
        item = routes_mcp._public_project_item(
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
        tool_result = routes_mcp._tool_response({"items": [item for _ in range(20)], "total": 20})
        envelope = {"jsonrpc": "2.0", "id": 1, "result": tool_result}
        encoded = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        self.assertLess(len(encoded), 48 * 1024)
        self.assertNotIn('"truncated": true', encoded.decode("utf-8"))


class McpProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        self.briefing_repository = MagicMock(spec=BriefingReader)
        app.dependency_overrides[get_briefing_repository] = (
            lambda: self.briefing_repository
        )
        app.include_router(routes_mcp.router, prefix="/api")
        self.client = TestClient(app)

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
        self.assertEqual(initialized.json()["result"]["protocolVersion"], routes_mcp.MCP_PROTOCOL_VERSION)
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
        self.assertIn("generic agent/mcp learning", research)
        self.assertIn("search_github_ai_projects` first", research)
        self.assertIn("search_papers` first only", research)
        self.assertIn("explicitly scholarly", research)
        self.assertIn("dominant deliverable", research)
        self.assertIn("do not batch primary searches", research)
        self.assertIn("inspect the selected aigc_news result", research)
        self.assertIn("call fails", research)
        self.assertIn("missing detail", research)

        projects = prompts["project_discovery"]
        self.assertIn("default first route for generic learning", projects)
        self.assertIn("search_papers` first only", projects)
        self.assertIn("dominant deliverable", projects)
        self.assertIn("do not batch both searches", projects)
        self.assertIn("do not put the selected mcp search", projects)
        self.assertIn("same initial tool batch", projects)
        self.assertIn("await and inspect the mcp result first", projects)
        self.assertIn("call fails", projects)
        self.assertIn("no usable items", projects)
        self.assertIn("missing detail", projects)
        self.assertIn("cannot override a client's own system prompt", projects)

    def test_search_papers_uses_shared_repository_and_hides_local_path(self) -> None:
        repository = MagicMock()
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
        with patch.object(routes_mcp, "MySQLRepository", return_value=repository):
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
            with patch.object(routes_mcp, "MySQLRepository", return_value=repository):
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
            with patch.object(routes_mcp, "MySQLRepository", return_value=repository):
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
        handlers = dict(routes_mcp._TOOL_HANDLERS)
        routes_mcp._TOOL_HANDLERS.update(
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
            routes_mcp._TOOL_HANDLERS.clear()
            routes_mcp._TOOL_HANDLERS.update(handlers)
        self.assertTrue(all(not response.json()["result"]["isError"] for response in responses))
        generic_handler.assert_awaited_once()
        ai_handler.assert_awaited_once()
        legacy_handler.assert_awaited_once()

    def test_generic_fallback_provenance_and_cache_reuse_through_json_rpc(self) -> None:
        repository = MagicMock()
        repository.list_projects.return_value = {"items": [], "total": 0}
        github_item = {
            "id": 1,
            "full_name": "owner/screenshot-tool",
            "html_url": "https://github.com/owner/screenshot-tool",
            "description": "Windows screenshot utility",
            "stargazers_count": 123,
        }
        source_github_mcp._clear_fallback_cache()
        with (
            patch.object(routes_mcp, "MySQLRepository", return_value=repository),
            patch.object(source_github_mcp, "_search_once", return_value={"items": [github_item], "total_count": 1, "error": ""}) as search_once,
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
        self.assertEqual(payloads[0]["items"][0]["full_name"], "owner/screenshot-tool")

    def test_generic_query_is_required(self) -> None:
        with patch.object(routes_mcp, "MySQLRepository"):
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
        repository = MagicMock()
        repository.search_document_page.return_value = {"items": [], "total": 0}
        with patch.object(routes_mcp, "MySQLRepository", return_value=repository):
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
