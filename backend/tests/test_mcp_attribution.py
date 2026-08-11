from __future__ import annotations

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
from backend.app.core.config import settings
from backend.app.services.dashboard.query_service import DashboardQueryService

TEST_BASE_URL = "https://aigcnews.cn"


class McpAttributionContractTests(unittest.TestCase):
    """MCP 回链契约：工具结果带 detail_url/attribution，日报 markdown 带来源行。"""

    def setUp(self) -> None:
        app = FastAPI()
        self.briefing_repository = MagicMock()
        self.documents = MagicMock()
        self.project_search_runtime = types.SimpleNamespace(
            search_projects=AsyncMock()
        )
        self.application_repositories = types.SimpleNamespace(
            documents=self.documents,
            rank_snapshots=MagicMock(),
            project_collections=MagicMock(),
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
        patcher = patch.object(settings, "public_base_url", TEST_BASE_URL)
        patcher.start()
        self.addCleanup(patcher.stop)

    def rpc(self, method: str, *, request_id=1, params=None):
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        return self.client.post("/api/mcp", json=payload)

    def call_tool(self, name: str, arguments: dict):
        result = self.rpc(
            "tools/call", params={"name": name, "arguments": arguments}
        ).json()["result"]
        self.assertFalse(result["isError"], result["content"][0]["text"])
        return result["structuredContent"]

    def test_search_papers_items_carry_detail_url_and_attribution(self) -> None:
        self.documents.search_document_page.return_value = {
            "items": [
                {"id": "2501.00001", "source": "arxiv", "title": "Paper A"},
                {"id": "news-1", "source": "news", "title": "News B"},
            ],
            "total": 2,
        }

        data = self.call_tool("search_papers", {"q": "agent"})

        self.assertEqual(
            data["attribution"], f"Data provided by AIGC Radar · {TEST_BASE_URL}"
        )
        arxiv_item, news_item = data["items"]
        self.assertEqual(
            arxiv_item["detail_url"],
            f"{TEST_BASE_URL}/papers/2501.00001/read"
            "?utm_source=mcp&utm_medium=tool",
        )
        self.assertIsNone(news_item["detail_url"])

    def test_paper_detail_includes_detail_url_and_attribution(self) -> None:
        self.documents.get_paper_detail.return_value = {
            "id": "paper-1",
            "source": "arxiv",
            "title": "Paper",
        }

        data = self.call_tool("get_paper_detail", {"paper_id": "paper-1"})

        self.assertEqual(
            data["item"]["detail_url"],
            f"{TEST_BASE_URL}/papers/paper-1/read?utm_source=mcp&utm_medium=tool",
        )
        self.assertIn("AIGC Radar", data["attribution"])

    def test_top_items_include_attribution(self) -> None:
        with patch.object(
            DashboardQueryService, "get_docs_for_date", return_value=[]
        ):
            data = self.call_tool("get_top_items", {"source": "all", "limit": 5})

        self.assertEqual(data["items"], [])
        self.assertEqual(
            data["attribution"], f"Data provided by AIGC Radar · {TEST_BASE_URL}"
        )

    def test_project_search_items_link_to_projects_view(self) -> None:
        self.project_search_runtime.search_projects.return_value = {
            "items": [{"full_name": "owner/repo", "stars": 1000}],
            "total": 1,
        }

        data = self.call_tool("search_github_ai_projects", {"q": "agent"})

        self.assertEqual(
            data["items"][0]["detail_url"],
            f"{TEST_BASE_URL}/projects?q=owner%2Frepo"
            "&utm_source=mcp&utm_medium=tool",
        )
        self.assertIn("AIGC Radar", data["attribution"])

    def test_report_latest_markdown_carries_source_footer(self) -> None:
        self.briefing_repository.get_briefing_by_date.return_value = {
            "content_zh": "# 日报正文",
            "content_en": "# Daily body",
        }

        zh = self.rpc(
            "resources/read", params={"uri": "aigc-news://report/latest"}
        ).json()["result"]["contents"][0]["text"]
        self.assertTrue(zh.startswith("# 日报正文"))
        self.assertIn("数据来源", zh)
        self.assertIn(
            f"{TEST_BASE_URL}/report?utm_source=mcp&utm_medium=resource", zh
        )

        en = self.rpc(
            "resources/read",
            request_id=2,
            params={"uri": "aigc-news://report/latest?locale=en"},
        ).json()["result"]["contents"][0]["text"]
        self.assertTrue(en.startswith("# Daily body"))
        self.assertIn("Source:", en)
        self.assertIn(
            f"{TEST_BASE_URL}/report?utm_source=mcp&utm_medium=resource", en
        )

    def test_base_url_falls_back_to_brand_site_when_unconfigured(self) -> None:
        with patch.object(settings, "public_base_url", None):
            self.documents.search_document_page.return_value = {
                "items": [{"id": "2501.00002", "source": "arxiv", "title": "P"}],
                "total": 1,
            }
            data = self.call_tool("search_papers", {"q": "agent"})

        self.assertEqual(
            data["items"][0]["detail_url"],
            "https://aigcnews.cn/papers/2501.00002/read"
            "?utm_source=mcp&utm_medium=tool",
        )
        self.assertEqual(
            data["attribution"], "Data provided by AIGC Radar · https://aigcnews.cn"
        )


if __name__ == "__main__":
    unittest.main()
