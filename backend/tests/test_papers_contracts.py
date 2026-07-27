from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.app.api.dependencies import get_document_repository
from backend.app.api.routes_papers import (
    _enrich_pdf_url,
    _extract_arxiv_id,
    _safe_doc,
    proxy_arxiv_pdf,
    router,
)


class _SearchRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    def search_documents(self, query: str, limit: int = 20, *, source=None):
        self.calls.append((query, limit))
        return [
            {
                "id": "paper-1",
                "source": "arxiv",
                "title": "Paper",
                "published_date": date(2026, 7, 27),
                "local_pdf_path": None,
            }
        ]


class _Cursor:
    def __init__(self, rows: list[dict[str, object] | None]) -> None:
        self._rows = iter(rows)
        self.executions: list[tuple[str, tuple[object, ...] | None]] = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql: str, params=None) -> None:
        self.executions.append((sql, params))

    def fetchall(self):
        row = next(self._rows)
        return row

    def fetchone(self):
        return next(self._rows)


class _Connection:
    def __init__(self, rows: list[dict[str, object] | None]) -> None:
        self.cursor_value = _Cursor(rows)
        self.commits = 0
        self.closes = 0

    def cursor(self):
        return self.cursor_value

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closes += 1


class _LegacyRepository:
    connections: list[_Connection] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    def _connect(self):
        return self.connections.pop(0)


class PapersContractsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = FastAPI()
        self.app.include_router(router, prefix="/api")

    def test_search_preserves_normalization_shape_and_forwarded_proto(self) -> None:
        repository = _SearchRepository()
        self.app.dependency_overrides[get_document_repository] = lambda: repository

        response = TestClient(self.app).get(
            "/api/papers/search",
            params={"q": "  agents  ", "limit": 7},
            headers={"x-forwarded-proto": "https"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(repository.calls, [("agents", 7)])
        self.assertEqual(body["q"], "agents")
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["published_date"], "2026-07-27")
        self.assertEqual(
            body["items"][0]["pdf_media_url"],
            "https://testserver/api/papers/paper-1/pdf",
        )

    def test_search_rejects_whitespace_and_query_bounds(self) -> None:
        repository = _SearchRepository()
        self.app.dependency_overrides[get_document_repository] = lambda: repository
        client = TestClient(self.app)

        whitespace = client.get("/api/papers/search", params={"q": "   "})
        missing = client.get("/api/papers/search")
        excessive_limit = client.get(
            "/api/papers/search", params={"q": "paper", "limit": 101}
        )

        self.assertEqual(whitespace.status_code, 422)
        self.assertEqual(whitespace.json()["detail"], "搜索关键词不能为空")
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(excessive_limit.status_code, 422)
        self.assertEqual(repository.calls, [])

    def test_safe_projection_and_media_urls_preserve_scalar_rules(self) -> None:
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "scheme": "http",
                "server": ("example.test", 80),
                "path": "/",
                "root_path": "",
                "query_string": b"",
                "headers": [(b"x-forwarded-proto", b"https")],
            }
        )
        safe = _safe_doc({"id": 1, "value": date(2026, 7, 27), "none": None})
        local = _enrich_pdf_url(
            {"id": "one", "source": "arxiv", "local_pdf_path": "/tmp/a/b.pdf"},
            request,
        )
        other = _enrich_pdf_url({"id": "two", "source": "news"}, request)

        self.assertEqual(safe, {"id": 1, "value": "2026-07-27", "none": None})
        self.assertEqual(local["pdf_media_url"], "https://example.test/api/media/papers/b.pdf")
        self.assertIsNone(other["pdf_media_url"])

    def test_top_today_uses_exact_today_then_fallback_order_and_lifecycle(self) -> None:
        connection = _Connection([[], [{"id": "fallback", "source": "arxiv"}]])
        _LegacyRepository.connections = [connection]

        with patch(
            "backend.app.repositories.mysql_repo.MySQLRepository", _LegacyRepository
        ):
            response = TestClient(self.app).get("/api/papers/top10-today")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["id"], "fallback")
        self.assertEqual(len(connection.cursor_value.executions), 2)
        today_sql, today_params = connection.cursor_value.executions[0]
        fallback_sql, fallback_params = connection.cursor_value.executions[1]
        self.assertIn("LEFT(created_at, 10) = %s", today_sql)
        self.assertIn("ORDER BY COALESCE(raw_score, score, 0) DESC", today_sql)
        self.assertEqual(len(today_params), 1)
        self.assertRegex(today_params[0], r"^\d{4}-\d{2}-\d{2}$")
        self.assertIn(
            "ORDER BY created_at DESC, COALESCE(raw_score, score, 0) DESC",
            fallback_sql,
        )
        self.assertIsNone(fallback_params)
        self.assertEqual(connection.commits, 2)
        self.assertEqual(connection.closes, 1)

    def test_detail_preserves_query_shape_not_found_and_lifecycle(self) -> None:
        found = _Connection([{"id": "paper-1", "source": "arxiv"}])
        missing = _Connection([None])
        _LegacyRepository.connections = [found, missing]

        with patch(
            "backend.app.repositories.mysql_repo.MySQLRepository", _LegacyRepository
        ):
            client = TestClient(self.app)
            response = client.get("/api/papers/paper-1")
            not_found = client.get("/api/papers/missing")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pdf_media_url"], "http://testserver/api/papers/paper-1/pdf")
        self.assertEqual(not_found.status_code, 404)
        self.assertEqual(not_found.json()["detail"], "Paper 'missing' not found")
        sql, params = found.cursor_value.executions[0]
        self.assertIn("WHERE id = %s", sql)
        self.assertIn("LIMIT 1", sql)
        self.assertEqual(params, ("paper-1",))
        self.assertEqual((found.commits, found.closes), (1, 1))
        self.assertEqual((missing.commits, missing.closes), (1, 1))

    def test_local_pdf_redirect_preserves_basename_and_forwarded_proto(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "cached.pdf")
            with open(path, "wb") as handle:
                handle.write(b"pdf")
            connection = _Connection(
                [{"local_pdf_path": path, "url": "", "source": "arxiv"}]
            )
            _LegacyRepository.connections = [connection]
            with patch(
                "backend.app.repositories.mysql_repo.MySQLRepository", _LegacyRepository
            ):
                response = TestClient(self.app).get(
                    "/api/papers/paper-1/pdf",
                    headers={"x-forwarded-proto": "https"},
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 307)
        self.assertEqual(
            response.headers["location"],
            "https://testserver/api/media/papers/cached.pdf",
        )
        self.assertEqual((connection.commits, connection.closes), (1, 1))

    def test_pdf_lookup_errors_and_arxiv_version_extraction(self) -> None:
        self.assertEqual(_extract_arxiv_id("https://arxiv.org/abs/2603.12255v2"), "2603.12255v2")
        self.assertIsNone(_extract_arxiv_id("not-an-arxiv-id"))
        missing = _Connection([None])
        invalid = _Connection([{"local_pdf_path": None, "url": "bad", "source": "arxiv"}])
        _LegacyRepository.connections = [missing, invalid]

        with patch(
            "backend.app.repositories.mysql_repo.MySQLRepository", _LegacyRepository
        ):
            client = TestClient(self.app)
            not_found = client.get("/api/papers/missing/pdf")
            unprocessable = client.get("/api/papers/bad/pdf")

        self.assertEqual((not_found.status_code, not_found.json()["detail"]), (404, "Paper not found"))
        self.assertEqual(
            (unprocessable.status_code, unprocessable.json()["detail"]),
            (422, "Cannot determine arxiv ID from paper URL"),
        )

    def test_remote_pdf_stream_preserves_request_headers_chunks_and_closure(self) -> None:
        events: list[str] = []

        class Response:
            status_code = 200

            async def __aenter__(self):
                events.append("response-enter")
                return self

            async def __aexit__(self, *args):
                events.append("response-close")

            async def aiter_bytes(self, chunk_size: int):
                self.chunk_size = chunk_size
                yield b"first"
                yield b"second"

        response = Response()

        class Client:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                events.append(f"client:{kwargs}")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                events.append("client-close")

            def stream(self, method, url, headers):
                self.request = (method, url, headers)
                events.append(f"request:{method}:{url}:{headers}")
                return response

        connection = _Connection(
            [{"local_pdf_path": None, "url": "https://arxiv.org/abs/2603.12255v3", "source": "arxiv"}]
        )
        _LegacyRepository.connections = [connection]
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "scheme": "http",
                "server": ("testserver", 80),
                "path": "/api/papers/paper-1/pdf",
                "root_path": "",
                "query_string": b"",
                "headers": [],
            }
        )

        async def consume():
            with patch(
                "backend.app.repositories.mysql_repo.MySQLRepository", _LegacyRepository
            ), patch("backend.app.api.routes_papers.httpx.AsyncClient", Client):
                streaming = await proxy_arxiv_pdf("paper-1", request)
                chunks = [chunk async for chunk in streaming.body_iterator]
                return streaming, chunks

        import asyncio

        streaming, chunks = asyncio.run(consume())
        self.assertEqual(chunks, [b"first", b"second"])
        self.assertEqual(response.chunk_size, 65536)
        self.assertEqual(streaming.media_type, "application/pdf")
        self.assertEqual(streaming.headers["content-disposition"], 'inline; filename="2603.12255v3.pdf"')
        self.assertEqual(streaming.headers["cache-control"], "public, max-age=86400")
        self.assertEqual(streaming.headers["access-control-allow-origin"], "*")
        self.assertIn("client:{'follow_redirects': True, 'timeout': 60.0}", events)
        self.assertTrue(any("request:GET:https://arxiv.org/pdf/2603.12255v3.pdf" in event for event in events))
        self.assertEqual(events[-2:], ["response-close", "client-close"])

    def test_remote_pdf_upstream_error_preserves_status_detail_and_closure(self) -> None:
        events: list[str] = []

        class Response:
            status_code = 503

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                events.append("response-close")

            async def aiter_bytes(self, chunk_size: int):
                if False:
                    yield b""

        class Client:
            def __init__(self, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                events.append("client-close")

            def stream(self, method, url, headers):
                return Response()

        connection = _Connection(
            [{"local_pdf_path": None, "url": "https://arxiv.org/abs/2603.12255", "source": "arxiv"}]
        )
        _LegacyRepository.connections = [connection]
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "scheme": "http",
                "server": ("testserver", 80),
                "path": "/",
                "root_path": "",
                "query_string": b"",
                "headers": [],
            }
        )

        async def consume():
            with patch(
                "backend.app.repositories.mysql_repo.MySQLRepository", _LegacyRepository
            ), patch("backend.app.api.routes_papers.httpx.AsyncClient", Client):
                streaming = await proxy_arxiv_pdf("paper-1", request)
                with self.assertRaises(HTTPException) as raised:
                    async for _ in streaming.body_iterator:
                        pass
                return raised.exception

        import asyncio

        error = asyncio.run(consume())
        self.assertEqual(error.status_code, 503)
        self.assertEqual(
            error.detail,
            "arxiv returned 503 for https://arxiv.org/pdf/2603.12255.pdf",
        )
        self.assertEqual(events, ["response-close", "client-close"])


if __name__ == "__main__":
    unittest.main()
