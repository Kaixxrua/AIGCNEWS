from __future__ import annotations

import asyncio
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

if "backend.app.core.config" not in sys.modules:
    config_module = types.ModuleType("backend.app.core.config")
    config_module.settings = types.SimpleNamespace(
        scheduler_timezone="Asia/Shanghai",
        mcp_github_fallback_enabled=True,
        mcp_github_fallback_use_token=False,
        mcp_github_fallback_timeout_seconds=8.0,
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

from backend.app.api import routes_papers
from backend.app.api.dependencies import get_document_repository
from backend.app.repositories.mysql_repo import (
    MySQLRepository,
    _document_search_candidates,
    _escape_like_literal,
    _normalize_document_search_query,
)


class DocumentQueryTests(unittest.TestCase):
    def test_learning_request_relaxes_to_agent(self) -> None:
        candidates = _document_search_candidates(
            "我想要学习Agent相关的内容，帮我找一点资料进行学习"
        )
        self.assertEqual(candidates[0], "我想要学习Agent相关的内容,帮我找一点资料进行学习")
        self.assertIn("Agent", candidates)
        self.assertNotIn("学习", candidates[1:])
        self.assertNotIn("资料", candidates[1:])

    def test_focused_queries_remain_whole_phrases(self) -> None:
        for query in ("Agent", "AI Agent", "LLM Agent", "MCP", "机器学习"):
            with self.subTest(query=query):
                self.assertEqual(_document_search_candidates(query), [query])

    def test_normalization_and_terms_are_bounded(self) -> None:
        self.assertEqual(_normalize_document_search_query("  ＡＩ   Agent  "), "AI Agent")
        candidates = _document_search_candidates(
            "help me find Agent agent MCP RAG planning memory tools tutorials examples"
        )
        relaxed = candidates[1:]
        self.assertLessEqual(len(relaxed), 6)
        self.assertEqual(len({item.casefold() for item in relaxed}), len(relaxed))

    def test_like_metacharacters_are_literal(self) -> None:
        self.assertEqual(_escape_like_literal("50%_done=ok"), "50=%=_done==ok")

    def test_repository_search_uses_shared_fields_and_stable_order(self) -> None:
        cursor = MagicMock()
        cursor.fetchone.return_value = {"cnt": 1}
        cursor.fetchall.return_value = [{"id": "doc-1", "title": "Agent"}]
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        repository = object.__new__(MySQLRepository)
        repository._connect = MagicMock(return_value=connection)

        rows = repository.search_documents(
            "我想要学习Agent相关的内容，帮我找一点资料进行学习",
            500,
        )

        self.assertEqual(rows, [{"id": "doc-1", "title": "Agent"}])
        sql, params = cursor.execute.call_args_list[-1].args
        normalized_sql = " ".join(sql.split())
        self.assertIn("COALESCE(title, '') LIKE %s ESCAPE '='", normalized_sql)
        self.assertIn("COALESCE(summary, '') LIKE %s ESCAPE '='", normalized_sql)
        self.assertIn("COALESCE(tags, '') LIKE %s ESCAPE '='", normalized_sql)
        self.assertIn("created_at DESC, id ASC", normalized_sql)
        self.assertIn("%Agent%", params)
        self.assertEqual(params[-2:], (100, 0))
        connection.close.assert_called_once()


class PaperRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(routes_papers.router, prefix="/api")
        self.repository = MagicMock()
        app.dependency_overrides[get_document_repository] = lambda: self.repository
        self.client = TestClient(app)

    def test_rest_search_trims_query_and_enriches_pdf(self) -> None:
        self.repository.search_documents.return_value = [
            {
                "id": "paper-1",
                "source": "arxiv",
                "title": "Agent Paper",
                "local_pdf_path": "/tmp/agent.pdf",
            }
        ]
        response = self.client.get(
            "/api/papers/search",
            params={"q": "  Agent  ", "limit": 100},
        )

        self.assertEqual(response.status_code, 200)
        self.repository.search_documents.assert_called_once_with("Agent", 100)
        payload = response.json()
        self.assertEqual(payload["q"], "Agent")
        self.assertEqual(payload["total"], 1)
        self.assertTrue(payload["items"][0]["pdf_media_url"].endswith("/api/media/papers/agent.pdf"))

    def test_rest_search_rejects_whitespace_query(self) -> None:
        response = self.client.get("/api/papers/search", params={"q": "   "})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
