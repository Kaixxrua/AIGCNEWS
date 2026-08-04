"""source_arxiv_mcp：HF 榜单解析、详情页解析与 arXiv API 补全契约测试。"""

from __future__ import annotations

import unittest
from datetime import datetime
from typing import Any
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup

from backend.app.services.ingestion import source_arxiv_mcp
from backend.app.services.ingestion.source_arxiv_mcp import (
    _enrich_with_arxiv_api,
    _extract_arxiv_id,
    _extract_daily_ids_from_html,
    _get_hf_base,
    _get_period_url,
    _normalize_arxiv_id,
    _parse_paper_detail,
    _parse_upvotes_from_card,
    fetch_latest_papers_async,
)


def _card(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


class TestArxivIdHelpers:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("/papers/2403.12345", "2403.12345"),
            ("2403.12345v2", "2403.12345v2"),
            ("https://huggingface.co/papers/2401.00001v3", "2401.00001v3"),
            ("no-id-here", None),
            ("", None),
        ],
    )
    def test_extract_arxiv_id(self, text: str, expected: str | None) -> None:
        assert _extract_arxiv_id(text) == expected

    @pytest.mark.parametrize(
        ("arxiv_id", "expected"),
        [("2403.12345v2", "2403.12345"), ("2403.12345", "2403.12345")],
    )
    def test_normalize_arxiv_id(self, arxiv_id: str, expected: str) -> None:
        assert _normalize_arxiv_id(arxiv_id) == expected


class TestParseUpvotes:
    def test_weighted_classes_win_over_plain_numbers(self) -> None:
        card = _card(
            '<article><span class="leading-none font-bold text-sm">42</span><div>99</div></article>'
        )
        assert _parse_upvotes_from_card(card.find("article")) == 42

    def test_semibold_beats_unweighted(self) -> None:
        card = _card('<article><div class="font-semibold">9</div><div>100</div></article>')
        assert _parse_upvotes_from_card(card.find("article")) == 9

    def test_no_numeric_text_returns_none(self) -> None:
        card = _card("<article><p>hello world</p></article>")
        assert _parse_upvotes_from_card(card.find("article")) is None


class TestExtractDailyIds:
    _HTML = """
    <article><a href="/papers/2403.11111">A</a><span class="leading-none">10</span></article>
    <article><a href="/papers/2403.22222v3">B</a><span class="leading-none">99</span></article>
    <article><a href="/papers/2403.11111">A dup</a><span class="leading-none">5</span></article>
    <article><a href="/other/page">no id</a></article>
    """

    def test_dedup_keeps_highest_upvotes_and_sorts_desc(self) -> None:
        pairs = _extract_daily_ids_from_html(self._HTML, limit=20)
        assert pairs == [("2403.22222", 99), ("2403.11111", 10)]

    def test_limit_keeps_top_n(self) -> None:
        assert _extract_daily_ids_from_html(self._HTML, limit=1) == [("2403.22222", 99)]

    def test_falls_back_to_h3_cards(self) -> None:
        html = '<h3><a href="/papers/2403.33333">X</a></h3>'
        assert _extract_daily_ids_from_html(html, limit=20) == [("2403.33333", 0)]


class TestPeriodUrls:
    def test_hf_base_defaults_and_mirror_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(source_arxiv_mcp.settings, "hf_endpoint", "")
        assert _get_hf_base() == "https://huggingface.co"
        monkeypatch.setattr(source_arxiv_mcp.settings, "hf_endpoint", " https://hf-mirror.com/ ")
        assert _get_hf_base() == "https://hf-mirror.com"

    def test_daily_weekly_monthly_urls(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(source_arxiv_mcp.settings, "hf_endpoint", "")
        dt = datetime(2026, 8, 4)  # ISO 2026-W32
        assert _get_period_url("daily", dt) == "https://huggingface.co/papers/date/2026-08-04"
        assert _get_period_url("weekly", dt) == "https://huggingface.co/papers/week/2026-W32"
        assert _get_period_url("monthly", dt) == "https://huggingface.co/papers/month/2026-08"
        assert _get_period_url("WEEKLY", dt) == "https://huggingface.co/papers/week/2026-W32"


class TestParsePaperDetail:
    _LONG_ABSTRACT = (
        "We propose a thoroughly tested method for synthetic benchmark evaluation "
        "that spans more than eighty characters in total."
    )
    _HTML = f"""
    <html><body>
    <h1>  Paper Title  </h1>
    <p>short</p>
    <p>{_LONG_ABSTRACT}</p>
    <p>thanks to the reviewers for their valuable feedback on this long paragraph of text.</p>
    <span class="author text-sm">Alice,</span>
    <span class="author">Bob</span>
    <time datetime="2024-03-01T00:00:00Z"></time>
    </body></html>
    """

    def test_parses_full_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # .env 可能配置 HF_ENDPOINT 镜像（如 hf-mirror.com），置空使 URL 断言确定
        monkeypatch.setattr(source_arxiv_mcp.settings, "hf_endpoint", "")
        doc = _parse_paper_detail(self._HTML, "2403.12345")
        assert doc is not None
        assert doc["title"] == "Paper Title"
        assert doc["abstract"] == self._LONG_ABSTRACT
        assert doc["authors"] == ["Alice", "Bob"]
        assert doc["published_date"] == "2024-03-01T00:00:00+00:00"
        assert doc["url"] == "https://huggingface.co/papers/2403.12345"
        assert doc["pdf_url"] == "https://arxiv.org/pdf/2403.12345"
        assert doc["original_arxiv_url"] == "https://arxiv.org/abs/2403.12345"
        assert doc["arxiv_id"] == "2403.12345"
        assert doc["source"] == "arxiv"
        assert doc["channel"] == "huggingface_daily_html"

    def test_title_falls_back_to_arxiv_id(self) -> None:
        doc = _parse_paper_detail("<html><body><p>nothing</p></body></html>", "2403.99999")
        assert doc is not None
        assert doc["title"] == "2403.99999"
        assert doc["abstract"] == ""
        assert doc["authors"] == []


class TestFetchLatestPapersAsync(unittest.IsolatedAsyncioTestCase):
    async def test_raises_when_listing_empty(self) -> None:
        async def fake_listing(**kwargs: Any):
            return ([], {}, "")

        with patch.object(source_arxiv_mcp, "_fetch_hf_listing_html", fake_listing):
            with self.assertRaises(RuntimeError):
                await fetch_latest_papers_async()

    async def test_raises_when_all_details_fail(self) -> None:
        async def fake_listing(**kwargs: Any):
            return (["2403.1"], {"2403.1": 3}, "2024-03-01")

        async def fake_details(*args: Any, **kwargs: Any):
            return []

        with (
            patch.object(source_arxiv_mcp, "_fetch_hf_listing_html", fake_listing),
            patch.object(source_arxiv_mcp, "_fetch_paper_details_async", fake_details),
        ):
            with self.assertRaises(RuntimeError):
                await fetch_latest_papers_async()

    async def test_happy_path_sets_snapshot_date_and_channel(self) -> None:
        captured: dict[str, Any] = {}

        async def fake_listing(period: str, limit: int, target_date: Any):
            captured["listing"] = (period, limit, target_date)
            return (["2403.1"], {"2403.1": 3}, "2024-03-01")

        async def fake_details(ids: list, upvotes: dict, source_channel: str = ""):
            captured["ids"] = ids
            captured["upvotes"] = upvotes
            captured["channel"] = source_channel
            return [{"arxiv_id": "2403.1", "title": "T"}]

        async def fake_enrich(docs: list):
            return docs

        with (
            patch.object(source_arxiv_mcp, "_fetch_hf_listing_html", fake_listing),
            patch.object(source_arxiv_mcp, "_fetch_paper_details_async", fake_details),
            patch.object(source_arxiv_mcp, "_enrich_with_arxiv_api", fake_enrich),
        ):
            result = await fetch_latest_papers_async(limit=5, period="weekly", target_date="2024-03-04")

        assert result == [{"arxiv_id": "2403.1", "title": "T", "snapshot_date": "2024-03-01"}]
        assert captured["channel"] == "huggingface_weekly_html"
        assert captured["listing"] == ("weekly", 5, datetime.fromisoformat("2024-03-04"))


class TestEnrichWithArxivApi(unittest.IsolatedAsyncioTestCase):
    _PATCH_TARGET = "backend.app.services.ingestion.arxiv_pdf_downloader._fetch_arxiv_metadata_by_ids"

    async def test_longer_abstract_wins_and_empty_fields_backfilled(self) -> None:
        docs = [
            {"arxiv_id": "2403.1", "abstract": "short", "authors": [], "published_date": ""},
            {"arxiv_id": "2403.2", "abstract": "x" * 500, "authors": ["A"], "published_date": "2024"},
            {"arxiv_id": "2403.3", "abstract": "keep", "authors": ["B"], "published_date": "2024"},
        ]
        api_papers = [
            {
                "arxiv_id": "2403.1",
                "abstract": "a much longer authoritative abstract from the arXiv API",
                "authors": ["Z"],
                "published_date": "2024-03-01",
            },
            {"arxiv_id": "2403.2", "abstract": "shorter", "authors": ["Y"], "published_date": "2024-01-01"},
        ]
        with patch(self._PATCH_TARGET, lambda ids: api_papers):
            result = await _enrich_with_arxiv_api(docs)

        doc1, doc2, doc3 = result
        assert doc1["abstract"] == "a much longer authoritative abstract from the arXiv API"
        assert doc1["authors"] == ["Z"]
        assert doc1["published_date"] == "2024-03-01"
        assert doc2["abstract"] == "x" * 500  # API 摘要更短 → 保留 HF 版本
        assert doc2["authors"] == ["A"]  # 已有作者 → 不回填
        assert doc2["published_date"] == "2024"
        assert doc3 == {"arxiv_id": "2403.3", "abstract": "keep", "authors": ["B"], "published_date": "2024"}

    async def test_api_failure_returns_docs_unchanged(self) -> None:
        docs = [{"arxiv_id": "2403.1", "abstract": "keep"}]

        def boom(ids: list) -> list:
            raise RuntimeError("api down")

        with patch(self._PATCH_TARGET, boom):
            result = await _enrich_with_arxiv_api(docs)
        assert result is docs
        assert docs[0]["abstract"] == "keep"

    async def test_no_arxiv_ids_skips_api_call(self) -> None:
        def guard(ids: list) -> list:
            raise AssertionError("不应调用 arXiv API")

        with patch(self._PATCH_TARGET, guard):
            assert await _enrich_with_arxiv_api([{"title": "no id"}]) == [{"title": "no id"}]
