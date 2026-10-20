from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import get_briefing_repository, get_document_repository
from backend.app.api.routes_sitemap import _iso_date, build_sitemap_xml, router
from backend.app.core.config import settings
from backend.app.repositories.briefing_repository import BriefingReader

TEST_BASE_URL = "https://sitemap.test"


class RecentDocumentsRepository:
    """DocumentRecentReader 间谍：记录查询参数并返回固定行。"""

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, str, int]] = []

    def list_recent_by_source(self, source: str, *, since_iso: str, limit: int = 500):
        self.calls.append((source, since_iso, limit))
        return self.rows


class SitemapRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_base_url = settings.public_base_url
        settings.public_base_url = TEST_BASE_URL
        self.repo = RecentDocumentsRepository(
            [
                {"id": "2608.01234", "published_at": "2026-08-10T12:00:00+00:00"},
                {"id": "2608.05678", "published_date": date(2026, 8, 9)},
                {"id": "dirty-time", "published_at": "not-a-date"},
                {"id": "  ", "published_at": "2026-08-01T00:00:00+00:00"},
            ]
        )
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.dependency_overrides[get_document_repository] = lambda: self.repo
        briefings = MagicMock(spec=BriefingReader)
        briefings.list_briefing_index.return_value = []
        app.dependency_overrides[get_briefing_repository] = lambda: briefings
        self.client = TestClient(app)

    def tearDown(self) -> None:
        settings.public_base_url = self._old_base_url

    def test_sitemap_lists_recent_arxiv_read_pages(self) -> None:
        response = self.client.get("/api/sitemap.xml")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers["content-type"].startswith("application/xml"))
        self.assertEqual(response.headers["cache-control"], "public, max-age=3600")

        body = response.text
        self.assertIn(f"<loc>{TEST_BASE_URL}/papers/2608.01234/read</loc>", body)
        self.assertIn("<lastmod>2026-08-10</lastmod>", body)
        self.assertIn(f"<loc>{TEST_BASE_URL}/papers/2608.05678/read</loc>", body)
        self.assertIn("<lastmod>2026-08-09</lastmod>", body)

    def test_sitemap_queries_arxiv_window_with_cap(self) -> None:
        response = self.client.get("/api/sitemap.xml")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.repo.calls), 1)
        source, since_iso, limit = self.repo.calls[0]
        self.assertEqual(source, "arxiv")
        self.assertEqual(limit, 5000)
        # 滚动窗口起点约为 90 天前（词法 ISO 串，宽松校验格式）。
        self.assertRegex(since_iso, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")

    def test_sitemap_skips_blank_ids_and_dirty_timestamps(self) -> None:
        response = self.client.get("/api/sitemap.xml")

        body = response.text
        # 空白 id 行被剔除；脏时间串保留 URL 但省略 lastmod。
        self.assertEqual(body.count("<url>"), 3)
        self.assertIn(f"<loc>{TEST_BASE_URL}/papers/dirty-time/read</loc>", body)
        self.assertEqual(body.count("<lastmod>"), 2)

    def test_builder_url_quotes_ids(self) -> None:
        xml = build_sitemap_xml([{"id": "a b&c", "published_at": None}], TEST_BASE_URL)
        self.assertIn(f"<loc>{TEST_BASE_URL}/papers/a%20b%26c/read</loc>", xml)


class IsoDateTests(unittest.TestCase):
    def test_extracts_date_prefix(self) -> None:
        self.assertEqual(_iso_date("2026-08-10T12:00:00+00:00"), "2026-08-10")
        self.assertEqual(_iso_date(date(2026, 8, 9)), "2026-08-09")

    def test_rejects_dirty_values(self) -> None:
        self.assertIsNone(_iso_date(None))
        self.assertIsNone(_iso_date(""))
        self.assertIsNone(_iso_date("2026/08/10"))


if __name__ == "__main__":
    unittest.main()
