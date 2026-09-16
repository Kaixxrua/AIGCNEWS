from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.app.api.dependencies import (
    get_document_repository,
    get_papers_repository,
)
from backend.app.api.routes_papers import router
from backend.app.core.config import settings
from backend.app.services.papers.presentation import (
    project_pdf_media_url,
    safe_document,
)


class SearchRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search_documents(self, query: str, limit: int = 20, *, source=None):
        self.calls.append((query, limit))
        return [{"id": "paper-1", "source": "arxiv", "published_date": date(2026, 7, 27)}]


class PapersRepository:
    def __init__(self) -> None:
        self.today: list[dict[str, object]] = []
        self.details: dict[str, dict[str, object]] = {}
        self.pdf_sources: dict[str, dict[str, object]] = {}
        self.calls: list[tuple[str, str | None]] = []

    def get_today_top_arxiv_documents(self):
        self.calls.append(("today", None))
        return self.today

    def get_paper_detail(self, paper_id: str):
        self.calls.append(("detail", paper_id))
        return self.details.get(paper_id)

    def get_paper_pdf_source(self, paper_id: str):
        self.calls.append(("pdf", paper_id))
        return self.pdf_sources.get(paper_id)




class PapersContractsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = FastAPI()
        self.app.include_router(router, prefix="/api")
        self.search = SearchRepository()
        self.papers = PapersRepository()
        self.app.dependency_overrides[get_document_repository] = lambda: self.search
        self.app.dependency_overrides[get_papers_repository] = lambda: self.papers

    def test_search_preserves_normalization_shape_and_ignores_forged_headers(self) -> None:
        response = TestClient(self.app).get(
            "/api/papers/search",
            params={"q": "  agents  ", "limit": 7},
            # Host 与 X-Forwarded-Proto 均可伪造：一律不采信，返回相对路径
            headers={"host": "evil.example", "x-forwarded-proto": "https"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.search.calls, [("agents", 7)])
        self.assertEqual(
            response.json(),
            {
                "items": [{
                    "id": "paper-1",
                    "source": "arxiv",
                    "published_date": "2026-07-27",
                    "pdf_media_url": None,
                }],
                "total": 1,
                "q": "agents",
            },
        )

    def test_search_rejects_whitespace_and_query_bounds(self) -> None:
        client = TestClient(self.app)
        self.assertEqual(client.get("/api/papers/search", params={"q": "   "}).status_code, 422)
        self.assertEqual(client.get("/api/papers/search").status_code, 422)
        self.assertEqual(client.get("/api/papers/search", params={"q": "x", "limit": 101}).status_code, 422)
        self.assertEqual(self.search.calls, [])

    def test_safe_projection_and_media_urls_preserve_scalar_rules(self) -> None:
        request = Request({
            "type": "http", "method": "GET", "scheme": "http",
            "server": ("example.test", 80), "path": "/", "root_path": "",
            "query_string": b"", "headers": [(b"x-forwarded-proto", b"https")],
        })
        self.assertEqual(safe_document({"id": 1, "value": date(2026, 7, 27)}), {"id": 1, "value": "2026-07-27"})
        local = project_pdf_media_url({"local_pdf_path": "/tmp/a/b.pdf"}, request)
        other = project_pdf_media_url({"id": "two", "source": "news"}, request)
        self.assertIsNone(local["pdf_media_url"])
        self.assertIsNone(other["pdf_media_url"])

    def test_retired_media_urls_remain_null_with_configured_origin(self) -> None:
        request = Request({
            "type": "http", "method": "GET", "scheme": "http",
            "server": ("example.test", 80), "path": "/", "root_path": "",
            "query_string": b"", "headers": [(b"host", b"evil.example")],
        })
        with patch.object(settings, "public_base_url", "https://aigcnews.cn/"):
            local = project_pdf_media_url({"local_pdf_path": "/tmp/a/b.pdf"}, request)
            proxied = project_pdf_media_url({"id": "paper-1", "source": "arxiv"}, request)
        # 绝对 URL 只来自配置化 origin；伪造的 Host 头不生效
        self.assertIsNone(local["pdf_media_url"])
        self.assertIsNone(proxied["pdf_media_url"])

    def test_top_and_detail_preserve_shapes_calls_and_not_found(self) -> None:
        self.papers.today = [{"id": "top", "source": "arxiv"}]
        self.papers.details["paper-1"] = {"id": "paper-1", "source": "arxiv"}
        client = TestClient(self.app)
        top = client.get("/api/papers/top10-today")
        detail = client.get("/api/papers/paper-1")
        missing = client.get("/api/papers/missing")
        self.assertEqual(top.json()["total"], 1)
        self.assertIsNone(detail.json()["pdf_media_url"])
        self.assertEqual((missing.status_code, missing.json()["detail"]), (404, "Paper 'missing' not found"))
        self.assertEqual(self.papers.calls, [("today", None), ("detail", "paper-1"), ("detail", "missing")])









    def test_pdf_reader_endpoint_is_retired_without_repository_access(self) -> None:
        response = TestClient(self.app).get("/api/papers/paper-1/pdf")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.papers.calls, [])


if __name__ == "__main__":
    unittest.main()
