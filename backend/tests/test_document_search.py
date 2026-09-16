from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_papers
from backend.app.api.dependencies import get_document_repository
from backend.app.domain.search_semantics import (
    escape_like_literal,
    normalize_search_query,
)
from backend.app.repositories.postgres_document_repository import (
    _document_search_candidates,
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
        self.assertEqual(normalize_search_query("  ＡＩ   Agent  "), "AI Agent")
        candidates = _document_search_candidates(
            "help me find Agent agent MCP RAG planning memory tools tutorials examples"
        )
        relaxed = candidates[1:]
        self.assertLessEqual(len(relaxed), 6)
        self.assertEqual(len({item.casefold() for item in relaxed}), len(relaxed))

    def test_like_metacharacters_are_literal(self) -> None:
        self.assertEqual(escape_like_literal("50%_done=ok"), "50=%=_done==ok")

class PaperRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(routes_papers.router, prefix="/api")
        self.repository = MagicMock()
        app.dependency_overrides[get_document_repository] = lambda: self.repository
        self.client = TestClient(app)

    def test_rest_search_trims_query_and_retires_local_pdf_delivery(self) -> None:
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
        self.assertIsNone(payload["items"][0]["pdf_media_url"])

    def test_rest_search_rejects_whitespace_query(self) -> None:
        response = self.client.get("/api/papers/search", params={"q": "   "})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
