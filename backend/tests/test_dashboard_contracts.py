from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from starlette.requests import Request

from backend.app.api import routes_dashboard
from backend.app.api.dependencies import get_rank_snapshot_repository


COMPATIBILITY_HELPERS = (
    "_compute_board_status",
    "_dedupe_docs",
    "_enrich_doc_pdf_url",
    "_get_docs_for_date",
    "_resolve_snapshot_date",
    "_score_categories",
)


class FakeRankSnapshotReader:
    def __init__(
        self,
        documents: dict[tuple[str, str, str], list[dict[str, Any]]] | None = None,
        yesterday_ids: set[str] | None = None,
    ) -> None:
        self.documents = documents or {}
        self.yesterday_ids = yesterday_ids or set()
        self.document_calls: list[tuple[str, str | None, str | None, int]] = []
        self.doc_id_calls: list[tuple[str, str | None]] = []

    def get_snapshot_documents(
        self,
        snapshot_date: str,
        source_channel: str | None = None,
        source_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        self.document_calls.append(
            (snapshot_date, source_channel, source_type, limit)
        )
        return list(
            self.documents.get(
                (snapshot_date, source_channel or "", source_type or ""), []
            )
        )

    def get_snapshot_dates(
        self,
        limit: int = 60,
        source: str | None = None,
        period: str | None = None,
    ) -> list[str]:
        return []

    def get_snapshot_source_counts(self, snapshot_date: str) -> dict[str, int]:
        return {}

    def get_snapshot_doc_ids(
        self,
        snapshot_date: str,
        source_channel: str | None = None,
    ) -> set[str]:
        self.doc_id_calls.append((snapshot_date, source_channel))
        return set(self.yesterday_ids)


def _request(path: str, query: str = "", proto: str | None = None) -> Request:
    headers = [] if proto is None else [(b"x-forwarded-proto", proto.encode())]
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "server": ("testserver", 80),
            "path": path,
            "query_string": query.encode(),
            "headers": headers,
        }
    )


def test_dashboard_compatibility_helpers_remain_importable() -> None:
    for helper_name in COMPATIBILITY_HELPERS:
        assert callable(getattr(routes_dashboard, helper_name))


def test_cache_key_preserves_namespace_function_path_and_sorted_query() -> None:
    request = _request(
        "/api/dashboard/top",
        "source=github&period=weekly&limit=7&date=2025-01-02",
    )

    key = routes_dashboard._dashboard_cache_key_builder(
        routes_dashboard.get_top_list,
        namespace="dashboard",
        request=request,
    )

    payload = {
        "path": "/api/dashboard/top",
        "namespace": "dashboard",
        "query": {
            "source": "github",
            "period": "weekly",
            "limit": "7",
            "date": "2025-01-02",
        },
    }
    digest = hashlib.md5(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert key == f"dashboard:get_top_list:{digest}"


def test_single_source_query_uses_exact_then_same_period_fallback_and_stops() -> None:
    date = "2025-01-02"
    fallback_doc = {"id": "fallback", "source": "github"}
    reader = FakeRankSnapshotReader(
        {
            (date, "github_hot_weekly", "github"): [fallback_doc],
            (date, "github_fallback", "github"): [{"id": "must-not-read"}],
        }
    )

    docs = routes_dashboard._get_docs_for_date(
        reader, date, "weekly", "github", 37
    )

    assert docs == [fallback_doc]
    assert reader.document_calls == [
        (date, "github_trending_weekly", "github", 37),
        (date, "github_hot_weekly", "github", 37),
    ]


def test_all_source_query_keeps_source_order_exact_channels_and_limit() -> None:
    date = "2025-01-02"
    reader = FakeRankSnapshotReader()

    assert routes_dashboard._get_docs_for_date(reader, date, "monthly", None, 41) == []

    assert reader.document_calls == [
        (date, "huggingface_monthly_html", "arxiv", 41),
        (date, "github_trending_monthly", "github", 41),
        (date, "github_hot_monthly", "github", 41),
        (date, "techmeme_daily_rss", "news", 41),
        (date, "producthunt_monthly_html", "producthunt", 41),
        (date, "hn_monthly_html", "hackernews", 41),
    ]


def test_daily_hackernews_excludes_yesterday_then_sorts_by_points() -> None:
    date = "2025-01-02"
    reader = FakeRankSnapshotReader(
        {
            (date, "hn_daily_html", "hackernews"): [
                {"id": "old", "source": "hackernews", "raw_score": 100},
                {"id": "low", "source": "hackernews", "raw_score": 2},
                {"id": "high", "source": "hackernews", "raw_score": 9},
            ]
        },
        yesterday_ids={"old"},
    )

    docs = routes_dashboard._get_docs_for_date(
        reader, date, "daily", "hackernews", 500
    )

    assert [doc["id"] for doc in docs] == ["high", "low"]
    assert reader.doc_id_calls == [("2025-01-01", "hn_daily_html")]


def test_top_route_preserves_dedupe_limit_and_forwarded_pdf_url() -> None:
    date = "2020-01-02"
    reader = FakeRankSnapshotReader(
        {
            (date, "github_trending_daily", "github"): [
                {
                    "id": "first",
                    "source": "github",
                    "url": "https://example.test/repo",
                    "local_pdf_path": "storage/papers/report.pdf",
                },
                {
                    "id": "duplicate",
                    "source": "github",
                    "url": "https://example.test/repo",
                },
                {
                    "id": "second",
                    "source": "github",
                    "url": "https://example.test/other",
                    "local_pdf_path": None,
                },
            ]
        }
    )
    app = FastAPI()
    app.include_router(routes_dashboard.router, prefix="/api")
    app.dependency_overrides[get_rank_snapshot_repository] = lambda: reader

    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract")
    try:
        response = TestClient(app).get(
            f"/api/dashboard/top?source=github&period=daily&limit=2&date={date}",
            headers={"X-Forwarded-Proto": "https"},
        )
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == ["first", "second"]
    assert payload["items"][0]["pdf_media_url"] == (
        "https://testserver/api/media/papers/report.pdf"
    )
    assert payload["items"][1]["pdf_media_url"] is None
    assert payload == {
        "items": payload["items"],
        "total": 2,
        "period": "daily",
        "snapshot_date": date,
        "is_finalized": True,
        "is_embargoed": False,
    }
    assert reader.document_calls == [
        (date, "github_trending_daily", "github", 500)
    ]


def test_radar_scoring_preserves_weighting_rounding_and_neutral_floor() -> None:
    assert routes_dashboard._score_categories([]) == [
        {"name": name, "value": 50}
        for name in ("大模型", "智能体", "多模态", "数据与评测", "系统与部署")
    ]

    radar = routes_dashboard._score_categories(
        [
            {"source": "github", "title": "LLM agent", "raw_score": 400},
            {"source": "news", "title": "image benchmark"},
        ]
    )
    assert radar == [
        {"name": "大模型", "value": 100},
        {"name": "智能体", "value": 100},
        {"name": "多模态", "value": 77},
        {"name": "数据与评测", "value": 77},
        {"name": "系统与部署", "value": 30},
    ]
