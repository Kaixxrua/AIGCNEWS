from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend
from starlette.requests import Request

from backend.app.api import routes_dashboard
from backend.app.api.dependencies import (
    get_document_repository,
    get_rank_snapshot_repository,
)
from backend.app.services.dashboard import policy
from backend.app.services.dashboard.query_service import DashboardQueryService

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


def test_x_source_query_reads_watchlist_channel_and_joins_daily_all() -> None:
    date = "2025-01-02"
    x_doc = {"id": "tweet", "source": "x"}
    reader = FakeRankSnapshotReader({(date, "x_daily_watchlist", "x"): [x_doc]})

    assert routes_dashboard._get_docs_for_date(reader, date, "daily", "x", 25) == [x_doc]
    assert reader.document_calls == [(date, "x_daily_watchlist", "x", 25)]

    # X 无周/月频道：单源周/月查询不产生任何读取
    weekly_reader = FakeRankSnapshotReader()
    assert routes_dashboard._get_docs_for_date(weekly_reader, date, "weekly", "x", 25) == []
    assert weekly_reader.document_calls == []

    # daily 混合流：x 频道在 hackernews 之后按序读取
    all_reader = FakeRankSnapshotReader()
    assert routes_dashboard._get_docs_for_date(all_reader, date, "daily", None, 41) == []
    assert all_reader.document_calls == [
        (date, "huggingface_daily_html", "arxiv", 41),
        (date, "github_trending_daily", "github", 41),
        (date, "github_hot_daily", "github", 41),
        (date, "github_fallback", "github", 41),
        (date, "techmeme_daily_rss", "news", 41),
        (date, "producthunt_daily_html", "producthunt", 41),
        (date, "hn_daily_html", "hackernews", 41),
        (date, "x_daily_watchlist", "x", 41),
    ]


def test_query_service_matches_legacy_fallback_output_and_call_order() -> None:
    date = "2025-01-02"
    documents = {
        (date, "github_hot_daily", "github"): [
            {"id": "fallback", "source": "github"}
        ],
        (date, "github_fallback", "github"): [{"id": "must-not-read"}],
    }
    legacy_reader = FakeRankSnapshotReader(documents)
    service_reader = FakeRankSnapshotReader(documents)

    legacy_docs = routes_dashboard._get_docs_for_date(
        legacy_reader, date, "daily", "github", 29
    )
    service_docs = DashboardQueryService(service_reader).get_docs_for_date(
        date, "daily", "github", 29
    )

    assert service_docs == legacy_docs
    assert service_reader.document_calls == legacy_reader.document_calls
    assert service_reader.doc_id_calls == legacy_reader.doc_id_calls


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

    service_reader = FakeRankSnapshotReader(
        reader.documents, yesterday_ids={"old"}
    )
    service_docs = DashboardQueryService(service_reader).get_docs_for_date(
        date, "daily", "hackernews", 500
    )
    assert service_docs == docs
    assert service_reader.document_calls == reader.document_calls
    assert service_reader.doc_id_calls == reader.doc_id_calls


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


def test_top_route_serves_limit_past_legacy_50_cap() -> None:
    date = "2020-01-02"
    docs = [
        {"id": f"t{i}", "source": "x", "url": f"https://x.com/a/status/{i}"}
        for i in range(60)
    ]
    reader = FakeRankSnapshotReader({(date, "x_daily_watchlist", "x"): docs})
    app = FastAPI()
    app.include_router(routes_dashboard.router, prefix="/api")
    app.dependency_overrides[get_rank_snapshot_repository] = lambda: reader

    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract")
    try:
        client = TestClient(app)
        ok = client.get(f"/api/dashboard/top?source=x&period=daily&limit=60&date={date}")
        too_big = client.get(
            f"/api/dashboard/top?source=x&period=daily&limit=501&date={date}"
        )
    finally:
        FastAPICache.reset()

    assert ok.status_code == 200
    assert len(ok.json()["items"]) == 60
    assert too_big.status_code == 422


def test_x_recent_route_serves_rolling_window_and_filters_stale_rows() -> None:
    now = datetime.now(timezone.utc)
    docs = [
        {"id": "x:new", "source": "x", "published_at": (now - timedelta(hours=1)).isoformat()},
        {"id": "x:edge", "source": "x", "published_at": (now - timedelta(hours=23, minutes=59)).isoformat()},
        # 超出 24h 窗口 / 无法解析 / 空值：路由层二次过滤剔除
        {"id": "x:stale", "source": "x", "published_at": (now - timedelta(hours=25)).isoformat()},
        {"id": "x:bad", "source": "x", "published_at": "not-a-date"},
        {"id": "x:empty", "source": "x", "published_at": ""},
    ]

    class FakeRecentReader:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, int]] = []

        def list_recent_by_source(self, source, *, since_iso, limit=500):
            self.calls.append((source, since_iso, limit))
            return docs

    reader = FakeRecentReader()
    app = FastAPI()
    app.include_router(routes_dashboard.router, prefix="/api")
    app.dependency_overrides[get_document_repository] = lambda: reader

    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract")
    try:
        client = TestClient(app)
        ok = client.get("/api/dashboard/x/recent?hours=24&limit=500")
        default = client.get("/api/dashboard/x/recent")
        bad_hours = client.get("/api/dashboard/x/recent?hours=0")
        bad_limit = client.get("/api/dashboard/x/recent?limit=501")
    finally:
        FastAPICache.reset()

    assert ok.status_code == 200
    payload = ok.json()
    assert [item["id"] for item in payload["items"]] == ["x:new", "x:edge"]
    assert payload["total"] == 2
    assert payload["window_hours"] == 24
    assert payload["is_embargoed"] is False
    assert payload["snapshot_date"] is None
    source, since_iso, limit = reader.calls[0]
    assert source == "x"
    assert limit == 500
    # since_iso ≈ 请求时刻 - 24h
    parsed_since = datetime.fromisoformat(since_iso)
    assert now - timedelta(hours=24, minutes=1) <= parsed_since <= now - timedelta(hours=23, minutes=59)
    assert default.status_code == 200
    assert bad_hours.status_code == 422
    assert bad_limit.status_code == 422


def test_top_route_preserves_x_media_metadata() -> None:
    snapshot_date = "2020-01-02"
    reader = FakeRankSnapshotReader(
        {
            (snapshot_date, "x_daily_watchlist", "x"): [
                {
                    "id": "x:1001",
                    "source": "x",
                    "source_channel": "x_daily_watchlist",
                    "url": "https://x.com/openai/status/1001",
                    "title": "tweet with media",
                    "raw_score": 100,
                    "media": [
                        {"type": "photo", "url": "https://pbs.twimg.com/a.jpg", "width": 1200, "height": 800}
                    ],
                },
                {
                    "id": "x:1002",
                    "source": "x",
                    "source_channel": "x_daily_watchlist",
                    "url": "https://x.com/openai/status/1002",
                    "title": "plain tweet",
                    "raw_score": 50,
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
            f"/api/dashboard/top?source=x&period=daily&limit=10&date={snapshot_date}",
        )
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 2
    assert payload["items"][0]["media"] == [
        {"type": "photo", "url": "https://pbs.twimg.com/a.jpg", "width": 1200, "height": 800}
    ]
    assert payload["items"][1].get("media") is None

    docs = [
        {
            "id": "github-weekly",
            "source": "github",
            "source_channel": "github_trending_weekly",
            "rank_in_period": 2,
            "raw_score": 200,
            "url": "https://example.test/repo",
            "title": "LLM image benchmark",
            "published_date": "2025-01-02",
        },
        {
            "id": "duplicate",
            "source": "github",
            "source_channel": "github_trending_weekly",
            "rank_in_period": 3,
            "raw_score": 500,
            "url": "https://example.test/repo",
        },
        {
            "id": "fallback-ignored",
            "source": "github",
            "source_channel": "github_hot_weekly",
            "rank_in_period": 1,
            "raw_score": 900,
            "url": "https://example.test/fallback",
        },
        {
            "id": "arxiv",
            "source": "arxiv",
            "source_channel": "huggingface_weekly_html",
            "raw_score": 12,
            "title": "agent inference",
            "created_at": "2025-01-01",
        },
    ]
    reference_date = date(2025, 1, 2)

    extracted_filtered = policy.filter_docs_by_period(
        docs, "weekly", reference_date=reference_date
    )

    assert [doc["id"] for doc in extracted_filtered] == [
        "github-weekly",
        "duplicate",
        "arxiv",
    ]
    assert [doc["id"] for doc in policy.dedupe_docs(extracted_filtered)] == [
        "github-weekly",
        "arxiv",
    ]
    assert policy.score_categories(docs) == routes_dashboard._score_categories(docs)


def test_extracted_policy_matches_legacy_date_and_pdf_projection() -> None:
    assert policy.compute_board_status("2020-01-02") == (
        routes_dashboard._compute_board_status("2020-01-02")
    )
    assert policy.resolve_snapshot_date("2025-01-02") == (
        routes_dashboard._resolve_snapshot_date("2025-01-02")
    )

    legacy_doc = {"local_pdf_path": "storage/papers/report.pdf"}
    extracted_doc = dict(legacy_doc)
    request = _request("/api/dashboard/top", proto="https")
    assert policy.enrich_doc_pdf_url(extracted_doc, request) == (
        routes_dashboard._enrich_doc_pdf_url(legacy_doc, request)
    )


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


class FakeDocumentStatistics:
    def get_source_counts(self) -> dict[str, int]:
        return {"arxiv": 5, "github": 461, "news": 7}

    def get_today_document_count(self) -> int:
        return 3


class FakeUserStatistics:
    def get_user_count(self) -> int:
        return 13

    def get_today_registered_user_count(self) -> int:
        return 0


def _summary_client(monkeypatch, catalog_factory) -> TestClient:
    from backend.app.api.dependencies import (
        get_document_repository,
        get_user_account_repository,
    )

    monkeypatch.setattr(routes_dashboard, "get_project_catalog_repository", catalog_factory)
    app = FastAPI()
    app.include_router(routes_dashboard.router, prefix="/api")
    app.dependency_overrides[get_rank_snapshot_repository] = lambda: FakeRankSnapshotReader()
    app.dependency_overrides[get_document_repository] = lambda: FakeDocumentStatistics()
    app.dependency_overrides[get_user_account_repository] = lambda: FakeUserStatistics()
    return TestClient(app)


def test_summary_github_stat_uses_project_library_count(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    class FakeCatalog:
        def list_projects(self, **kwargs: Any) -> dict[str, Any]:
            calls.append(kwargs)
            return {"items": [], "total": 6983, "page": 1, "page_size": 1}

    client = _summary_client(monkeypatch, lambda: FakeCatalog())
    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract")
    try:
        response = client.get("/api/dashboard/summary?period=daily&date=2020-01-02")
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    stats = response.json()["stats"]
    assert stats["source_counts"] == {"arxiv": 5, "github": 6983, "news": 7}
    assert stats["total_documents"] == 5 + 6983 + 7
    assert calls == [
        {"source": "github", "scope": "all", "page": 1, "page_size": 1, "sort": "stars"}
    ]


def test_summary_github_stat_falls_back_to_documents_when_catalog_unavailable(monkeypatch) -> None:
    def broken_factory():
        raise RuntimeError("catalog down")

    client = _summary_client(monkeypatch, broken_factory)
    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract")
    try:
        response = client.get("/api/dashboard/summary?period=weekly&date=2020-01-02")
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    stats = response.json()["stats"]
    assert stats["source_counts"] == {"arxiv": 5, "github": 461, "news": 7}
    assert stats["total_documents"] == 5 + 461 + 7
