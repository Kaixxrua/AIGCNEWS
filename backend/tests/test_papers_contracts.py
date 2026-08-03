from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.app.api.dependencies import (
    get_document_repository,
    get_papers_repository,
    get_pdf_relay,
)
from backend.app.api.routes_papers import proxy_arxiv_pdf, router
from backend.app.services.papers.arxiv_identity import extract_arxiv_id
from backend.app.services.papers.pdf_relay import HttpxPdfRelay
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


class FakeRelay:
    def __init__(self, chunks=(b"first", b"second"), error: HTTPException | None = None):
        self.chunks = chunks
        self.error = error
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.closed = False

    async def stream(self, url: str, headers: dict[str, str]):
        self.calls.append((url, headers))
        try:
            if self.error:
                raise self.error
            for chunk in self.chunks:
                yield chunk
        finally:
            self.closed = True


class PapersContractsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = FastAPI()
        self.app.include_router(router, prefix="/api")
        self.search = SearchRepository()
        self.papers = PapersRepository()
        self.relay = FakeRelay()
        self.app.dependency_overrides[get_document_repository] = lambda: self.search
        self.app.dependency_overrides[get_papers_repository] = lambda: self.papers
        self.app.dependency_overrides[get_pdf_relay] = lambda: self.relay

    def test_search_preserves_normalization_shape_and_forwarded_proto(self) -> None:
        response = TestClient(self.app).get(
            "/api/papers/search",
            params={"q": "  agents  ", "limit": 7},
            headers={"x-forwarded-proto": "https"},
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
                    "pdf_media_url": "https://testserver/api/papers/paper-1/pdf",
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
        self.assertEqual(local["pdf_media_url"], "https://example.test/api/media/papers/b.pdf")
        self.assertIsNone(other["pdf_media_url"])

    def test_top_and_detail_preserve_shapes_calls_and_not_found(self) -> None:
        self.papers.today = [{"id": "top", "source": "arxiv"}]
        self.papers.details["paper-1"] = {"id": "paper-1", "source": "arxiv"}
        client = TestClient(self.app)
        top = client.get("/api/papers/top10-today")
        detail = client.get("/api/papers/paper-1")
        missing = client.get("/api/papers/missing")
        self.assertEqual(top.json()["total"], 1)
        self.assertEqual(detail.json()["pdf_media_url"], "http://testserver/api/papers/paper-1/pdf")
        self.assertEqual((missing.status_code, missing.json()["detail"]), (404, "Paper 'missing' not found"))
        self.assertEqual(self.papers.calls, [("today", None), ("detail", "paper-1"), ("detail", "missing")])

    def test_local_pdf_redirect_preserves_basename_and_forwarded_proto(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "cached.pdf")
            with open(path, "wb") as handle:
                handle.write(b"pdf")
            self.papers.pdf_sources["paper-1"] = {"local_pdf_path": path, "url": "", "source": "arxiv"}
            response = TestClient(self.app).get(
                "/api/papers/paper-1/pdf",
                headers={"x-forwarded-proto": "https"},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "https://testserver/api/media/papers/cached.pdf")

    def test_pdf_lookup_errors_and_arxiv_version_extraction(self) -> None:
        self.assertEqual(extract_arxiv_id("https://arxiv.org/abs/2603.12255v2"), "2603.12255v2")
        self.assertIsNone(extract_arxiv_id("not-an-arxiv-id"))
        self.papers.pdf_sources["bad"] = {"local_pdf_path": None, "url": "bad", "source": "arxiv"}
        client = TestClient(self.app)
        missing = client.get("/api/papers/missing/pdf")
        invalid = client.get("/api/papers/bad/pdf")
        self.assertEqual((missing.status_code, missing.json()["detail"]), (404, "Paper not found"))
        self.assertEqual((invalid.status_code, invalid.json()["detail"]), (422, "Cannot determine arxiv ID from paper URL"))

    def test_remote_pdf_preserves_url_headers_chunks_response_and_closure(self) -> None:
        self.papers.pdf_sources["paper-1"] = {
            "local_pdf_path": None,
            "url": "https://arxiv.org/abs/2603.12255v3",
            "source": "arxiv",
        }
        response = TestClient(self.app).get("/api/papers/paper-1/pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"firstsecond")
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertEqual(response.headers["content-disposition"], 'inline; filename="2603.12255v3.pdf"')
        self.assertEqual(response.headers["cache-control"], "public, max-age=86400")
        self.assertEqual(response.headers["access-control-allow-origin"], "*")
        self.assertEqual(self.relay.calls[0][0], "https://arxiv.org/pdf/2603.12255v3.pdf")
        self.assertEqual(self.relay.calls[0][1]["Accept"], "application/pdf,*/*")
        self.assertTrue(self.relay.closed)

    def test_remote_pdf_upstream_error_preserves_status_detail_and_closure(self) -> None:
        error = HTTPException(status_code=503, detail="arxiv returned 503 for https://arxiv.org/pdf/2603.12255.pdf")
        relay = FakeRelay(error=error)
        self.papers.pdf_sources["paper-1"] = {
            "local_pdf_path": None, "url": "https://arxiv.org/abs/2603.12255", "source": "arxiv"
        }
        request = Request({
            "type": "http", "method": "GET", "scheme": "http",
            "server": ("testserver", 80), "path": "/", "root_path": "",
            "query_string": b"", "headers": [],
        })

        async def consume():
            streaming = await proxy_arxiv_pdf("paper-1", request, self.papers, relay)
            with self.assertRaises(HTTPException) as raised:
                async for _ in streaming.body_iterator:
                    pass
            return raised.exception

        raised = asyncio.run(consume())
        self.assertEqual((raised.status_code, raised.detail), (503, error.detail))
        self.assertTrue(relay.closed)

    def test_httpx_relay_preserves_transport_options_chunk_size_and_closure(self) -> None:
        events: list[str] = []

        class Response:
            status_code = 200
            async def __aenter__(self): return self
            async def __aexit__(self, *args): events.append("response-close")
            async def aiter_bytes(self, chunk_size: int):
                events.append(f"chunk:{chunk_size}")
                yield b"pdf"

        class Client:
            def __init__(self, **kwargs): events.append(f"client:{kwargs}")
            async def __aenter__(self): return self
            async def __aexit__(self, *args): events.append("client-close")
            def stream(self, method, url, headers):
                events.append(f"request:{method}:{url}:{headers['Accept']}")
                return Response()

        async def consume():
            with patch("backend.app.services.papers.pdf_relay.httpx.AsyncClient", Client):
                return [chunk async for chunk in HttpxPdfRelay().stream("https://arxiv.test/a.pdf", {"Accept": "application/pdf,*/*"})]

        self.assertEqual(asyncio.run(consume()), [b"pdf"])
        self.assertEqual(events[0], "client:{'follow_redirects': True, 'timeout': 60.0}")
        self.assertIn("chunk:65536", events)
        self.assertEqual(events[-2:], ["response-close", "client-close"])

    def test_httpx_relay_preserves_upstream_error_and_closure(self) -> None:
        events: list[str] = []

        class Response:
            status_code = 502
            async def __aenter__(self): return self
            async def __aexit__(self, *args): events.append("response-close")

        class Client:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): events.append("client-close")
            def stream(self, method, url, headers): return Response()

        async def consume():
            with patch("backend.app.services.papers.pdf_relay.httpx.AsyncClient", Client):
                with self.assertRaises(HTTPException) as raised:
                    async for _ in HttpxPdfRelay().stream("https://arxiv.test/a.pdf", {}):
                        pass
                return raised.exception

        raised = asyncio.run(consume())
        self.assertEqual((raised.status_code, raised.detail), (502, "arxiv returned 502 for https://arxiv.test/a.pdf"))
        self.assertEqual(events, ["response-close", "client-close"])


if __name__ == "__main__":
    unittest.main()
