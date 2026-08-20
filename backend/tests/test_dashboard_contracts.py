from __future__ import annotations

import asyncio
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
    get_github_hot_board_reader,
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
        dates: list[str] | None = None,
    ) -> None:
        self.documents = documents or {}
        self.yesterday_ids = yesterday_ids or set()
        self.dates = list(dates or [])
        self.document_calls: list[tuple[str, str | None, str | None, int]] = []
        self.date_calls: list[tuple[int, str | None, str | None]] = []
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
        self.date_calls.append((limit, source, period))
        return list(self.dates[:limit])

    def get_snapshot_source_counts(self, snapshot_date: str) -> dict[str, int]:
        return {}

    def get_snapshot_doc_ids(
        self,
        snapshot_date: str,
        source_channel: str | None = None,
    ) -> set[str]:
        self.doc_id_calls.append((snapshot_date, source_channel))
        return set(self.yesterday_ids)


class FakeGitHubHotReader:
    """看板 github 榜 v5 热度读取假实现，按 metric_date 供给指标行。"""

    def __init__(
        self,
        rows: dict[str, list[dict[str, Any]]] | None = None,
        dates: list[str] | None = None,
    ) -> None:
        self.rows = rows or {}
        self.dates = list(dates or [])
        self.hot_calls: list[tuple[str, int]] = []
        self.date_calls: list[int] = []

    def list_github_hot_for_date(
        self,
        *,
        metric_date: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        self.hot_calls.append((metric_date, limit))
        return list(self.rows.get(metric_date, []))[:limit]

    def list_github_hot_dates(self, *, limit: int = 60) -> list[str]:
        self.date_calls.append(limit)
        return list(self.dates[:limit])


def _github_metric_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "repo_id": "owner/repo",
        "full_name": "owner/repo",
        "title": "repo",
        "url": "https://github.com/owner/repo",
        "description": "LLM agent framework",
        "language": "Python",
        "topics_json": '["llm", "agents"]',
        "stars": 12000,
        "forks": 800,
        "watchers": 150,
        "daily_star_growth": 514,
        "daily_growth_source": "snapshot_delta",
        "previous_snapshot_date": "2026-08-09",
        "hot_score": 96.5,
        "growth_suspicion_score": 0.4,
        "growth_suspicion_signals": '["low_fork_follow"]',
        "growth_corroborated": False,
        "metric_date": "2026-08-10",
    }
    row.update(overrides)
    return row


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
        "source=github&limit=7&date=2025-01-02",
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
            "limit": "7",
            "date": "2025-01-02",
        },
    }
    digest = hashlib.md5(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    assert key == f"dashboard:get_top_list:{digest}"


def test_cache_key_ignores_frontend_cache_buster_param() -> None:
    first = routes_dashboard._dashboard_cache_key_builder(
        routes_dashboard.get_x_recent,
        namespace="dashboard",
        request=_request("/api/dashboard/x/recent", "hours=24&limit=500&_t=111"),
    )
    second = routes_dashboard._dashboard_cache_key_builder(
        routes_dashboard.get_x_recent,
        namespace="dashboard",
        request=_request("/api/dashboard/x/recent", "hours=24&limit=500&_t=222"),
    )
    # _t 只穿透浏览器/中间层缓存，不进服务端 key：不同 _t 同 key 才能命中缓存
    assert first == second


def test_x_recent_cache_ttl_covers_ingest_cadence() -> None:
    """x/recent 冷算 ~2.3s：TTL 必须覆盖采集 cadence（5 分钟一轮）。

    采集成功后 clear_and_warm_dashboard_cache 先清后暖本 key，新鲜度由
    「距上次采集」界定；TTL 回退到 cadence 以下（如历史 120s）会让两轮
    采集间隙的访问必然 MISS 付冷算。
    """
    import inspect
    import re

    source = inspect.getsource(routes_dashboard.get_x_recent)
    match = re.search(r"@cache\(expire=(\d+)", source)
    assert match is not None, "get_x_recent 缺少 @cache(expire=...) 装饰器"
    assert int(match.group(1)) >= 300


def test_cache_key_ignores_unknown_params_but_separates_whitelisted_ones() -> None:
    baseline = routes_dashboard._dashboard_cache_key_builder(
        routes_dashboard.get_top_list,
        namespace="dashboard",
        request=_request("/api/dashboard/top", "limit=10"),
    )
    # 白名单外的随机参数不进 key：匿名用户无法用随机参数写爆 Redis。
    # period 已随看板周/月榜下线，同样被忽略（不再切分缓存）。
    with_junk = routes_dashboard._dashboard_cache_key_builder(
        routes_dashboard.get_top_list,
        namespace="dashboard",
        request=_request(
            "/api/dashboard/top",
            "limit=10&period=weekly&bogus=1&_t=999&aaa=zzz",
        ),
    )
    assert baseline == with_junk

    # 白名单参数仍隔离缓存：业务参数变化必须是新 key
    other_limit = routes_dashboard._dashboard_cache_key_builder(
        routes_dashboard.get_top_list,
        namespace="dashboard",
        request=_request("/api/dashboard/top", "limit=20"),
    )
    other_hours = routes_dashboard._dashboard_cache_key_builder(
        routes_dashboard.get_x_recent,
        namespace="dashboard",
        request=_request("/api/dashboard/x/recent", "hours=48"),
    )
    default_hours = routes_dashboard._dashboard_cache_key_builder(
        routes_dashboard.get_x_recent,
        namespace="dashboard",
        request=_request("/api/dashboard/x/recent", "hours=24"),
    )
    assert baseline != other_limit
    assert other_hours != default_hours


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


def test_top_route_preserves_dedupe_limit_and_relative_pdf_url() -> None:
    date = "2020-01-02"
    reader = FakeRankSnapshotReader(
        {
            (date, "huggingface_daily_html", "arxiv"): [
                {
                    "id": "first",
                    "source": "arxiv",
                    "url": "https://example.test/paper",
                    "local_pdf_path": "storage/papers/report.pdf",
                },
                {
                    "id": "duplicate",
                    "source": "arxiv",
                    "url": "https://example.test/paper",
                },
                {
                    "id": "second",
                    "source": "arxiv",
                    "url": "https://example.test/other",
                    "local_pdf_path": None,
                },
            ]
        }
    )
    app = FastAPI()
    app.include_router(routes_dashboard.router, prefix="/api")
    app.dependency_overrides[get_rank_snapshot_repository] = lambda: reader
    app.dependency_overrides[get_github_hot_board_reader] = lambda: FakeGitHubHotReader()

    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract")
    try:
        response = TestClient(app).get(
            f"/api/dashboard/top?source=arxiv&limit=2&date={date}",
            headers={"X-Forwarded-Proto": "https"},
        )
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == ["first", "second"]
    # pdf_media_url 不采信可伪造的 Host/X-Forwarded-Proto：默认相对路径
    assert payload["items"][0]["pdf_media_url"] == (
        "/api/media/papers/report.pdf"
    )
    assert payload["items"][1]["pdf_media_url"] is None
    assert payload == {
        "items": payload["items"],
        "total": 2,
        "period": "daily",
        "snapshot_date": date,
        "requested_date": date,
        "resolved_date": date,
        "stale": False,
        "is_finalized": True,
        "is_embargoed": False,
        # 分源定稿契约（PR1）：wire 只增不破，新字段纳入精确形状断言
        "source_status": policy.compute_source_status_map(date),
    }
    # 显式 date 不回溯：不触发可用日期查询
    assert reader.date_calls == []
    assert reader.document_calls == [
        (date, "huggingface_daily_html", "arxiv", 500)
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
        ok = client.get(f"/api/dashboard/top?source=x&limit=60&date={date}")
        too_big = client.get(
            f"/api/dashboard/top?source=x&limit=501&date={date}"
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
            self.calls: list[tuple[str, str, str | None, int]] = []

        def list_recent_by_source(self, source, *, since_iso, until_iso=None, limit=500):
            self.calls.append((source, since_iso, until_iso, limit))
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
        bad_days_back = client.get("/api/dashboard/x/recent?days_back=-1")
        too_far_back = client.get("/api/dashboard/x/recent?days_back=61")
    finally:
        FastAPICache.reset()

    assert ok.status_code == 200
    payload = ok.json()
    assert [item["id"] for item in payload["items"]] == ["x:new", "x:edge"]
    assert payload["total"] == 2
    assert payload["window_hours"] == 24
    assert payload["days_back"] == 0
    assert payload["is_embargoed"] is False
    assert payload["snapshot_date"] is None
    source, since_iso, until_iso, limit = reader.calls[0]
    assert source == "x"
    assert limit == 500
    # [since_iso, until_iso] ≈ [请求时刻 - 24h, 请求时刻]（days_back=0 窗口上界即当下）
    parsed_since = datetime.fromisoformat(since_iso)
    parsed_until = datetime.fromisoformat(str(until_iso))
    assert now - timedelta(hours=24, minutes=1) <= parsed_since <= now - timedelta(hours=23, minutes=59)
    assert now - timedelta(minutes=1) <= parsed_until <= now + timedelta(minutes=1)
    assert default.status_code == 200
    assert bad_hours.status_code == 422
    assert bad_limit.status_code == 422
    assert bad_days_back.status_code == 422
    assert too_far_back.status_code == 422


def test_x_recent_days_back_shifts_the_window_by_whole_days() -> None:
    now = datetime.now(timezone.utc)
    docs = [
        {"id": "x:today", "source": "x", "published_at": (now - timedelta(hours=2)).isoformat()},
        {"id": "x:yesterday", "source": "x", "published_at": (now - timedelta(hours=25)).isoformat()},
        {"id": "x:yesterday-edge", "source": "x", "published_at": (now - timedelta(hours=47, minutes=59)).isoformat()},
        # 落在回移窗口之外：太新（今天）/太旧（前天）
        {"id": "x:two-days", "source": "x", "published_at": (now - timedelta(hours=49)).isoformat()},
    ]

    class FakeRecentReader:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str | None, int]] = []

        def list_recent_by_source(self, source, *, since_iso, until_iso=None, limit=500):
            self.calls.append((source, since_iso, until_iso, limit))
            return docs

    reader = FakeRecentReader()
    app = FastAPI()
    app.include_router(routes_dashboard.router, prefix="/api")
    app.dependency_overrides[get_document_repository] = lambda: reader

    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract-xrecent-daysback")
    try:
        client = TestClient(app)
        shifted = client.get("/api/dashboard/x/recent?hours=24&days_back=1&limit=500")
    finally:
        FastAPICache.reset()

    assert shifted.status_code == 200
    payload = shifted.json()
    # days_back=1：只留 [now-48h, now-24h] 区间内的推文
    assert [item["id"] for item in payload["items"]] == ["x:yesterday", "x:yesterday-edge"]
    assert payload["days_back"] == 1
    _, since_iso, until_iso, _ = reader.calls[0]
    parsed_since = datetime.fromisoformat(since_iso)
    parsed_until = datetime.fromisoformat(str(until_iso))
    # 窗口上界 ≈ 请求时刻 - 24h，下界再往前 24h
    assert now - timedelta(hours=24, minutes=1) <= parsed_until <= now - timedelta(hours=23, minutes=59)
    assert now - timedelta(hours=48, minutes=1) <= parsed_since <= now - timedelta(hours=47, minutes=59)


def test_x_recent_short_cache_ignores_frontend_cache_buster() -> None:
    now = datetime.now(timezone.utc)
    docs = [
        {"id": "x:new", "source": "x", "published_at": (now - timedelta(hours=1)).isoformat()},
    ]

    class FakeRecentReader:
        def __init__(self) -> None:
            self.calls = 0

        def list_recent_by_source(self, source, *, since_iso, until_iso=None, limit=500):
            self.calls += 1
            return docs

    reader = FakeRecentReader()
    app = FastAPI()
    app.include_router(routes_dashboard.router, prefix="/api")
    app.dependency_overrides[get_document_repository] = lambda: reader

    # InMemoryBackend._store 是类级共享存储：用独立 prefix 隔离本测试的
    # 缓存条目，避免与文件中其他 x/recent 用例的同 key 条目互相污染
    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract-xrecent-cache")
    try:
        client = TestClient(app)
        first = client.get("/api/dashboard/x/recent?hours=24&limit=500&_t=111")
        second = client.get("/api/dashboard/x/recent?hours=24&limit=500&_t=222")
        # _t 不进缓存 key：相同业务参数的重复访问命中 120s 短缓存，只读一次库
        assert reader.calls == 1
        other_params = client.get("/api/dashboard/x/recent?hours=48&limit=500&_t=333")
        shifted = client.get("/api/dashboard/x/recent?hours=24&days_back=1&limit=500&_t=444")
    finally:
        FastAPICache.reset()

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["items"] == first.json()["items"]
    # 业务参数变化（含 days_back）仍是新 key，照常读库
    assert other_params.status_code == 200
    assert shifted.status_code == 200
    assert reader.calls == 3


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
            f"/api/dashboard/top?source=x&limit=10&date={snapshot_date}",
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


class FakeSiteVisits:
    def get_visit_stats(self, day) -> Any:
        from backend.app.repositories.site_visit_repository import SiteVisitStats

        return SiteVisitStats(today_visits=7, total_visits=700)

    def record_visit(self, day) -> Any:
        from backend.app.repositories.site_visit_repository import SiteVisitStats

        return SiteVisitStats(today_visits=8, total_visits=701)


def _summary_client(monkeypatch, catalog_factory, reader=None, github_hot=None) -> TestClient:
    from backend.app.api.dependencies import (
        get_document_repository,
        get_project_catalog_query_service,
        get_user_account_repository,
    )
    from backend.app.services.project_catalog.query_service import (
        ProjectCatalogQueryService,
    )

    app = FastAPI()
    app.include_router(routes_dashboard.router, prefix="/api")
    app.dependency_overrides[get_rank_snapshot_repository] = (
        lambda: reader if reader is not None else FakeRankSnapshotReader()
    )
    app.dependency_overrides[get_document_repository] = lambda: FakeDocumentStatistics()
    app.dependency_overrides[get_user_account_repository] = lambda: FakeUserStatistics()
    app.dependency_overrides[get_project_catalog_query_service] = (
        lambda: ProjectCatalogQueryService(repository_factory=catalog_factory)
    )
    app.dependency_overrides[get_github_hot_board_reader] = (
        lambda: github_hot if github_hot is not None else FakeGitHubHotReader()
    )
    app.dependency_overrides[routes_dashboard.get_site_visit_repository] = (
        lambda: FakeSiteVisits()
    )
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
        response = client.get("/api/dashboard/summary?date=2020-01-02")
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0, must-revalidate"
    assert response.headers["pragma"] == "no-cache"
    stats = response.json()["stats"]
    assert stats["source_counts"] == {"arxiv": 5, "github": 6983, "news": 7}
    assert stats["total_documents"] == 5 + 6983 + 7
    assert stats["today_visits"] == 7
    assert stats["total_visits"] == 700
    assert stats["today_unique_visitors"] == 7
    assert isinstance(stats["mcp_total_calls"], int)
    assert isinstance(stats["mcp_dsh_calls"], int)
    assert calls == [
        {"source": "github", "scope": "all", "page": 1, "page_size": 1, "sort": "stars"}
    ]


def test_summary_static_is_cacheable_without_dynamic_stats(monkeypatch) -> None:
    client = _summary_client(monkeypatch, lambda: object())
    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract-static-summary")
    try:
        response = client.get("/api/dashboard/summary-static?date=2020-01-02")
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    body = response.json()
    assert "stats" not in body
    assert {"top_list", "radar", "snapshot_date", "is_finalized", "is_embargoed"} <= body.keys()


def test_summary_reads_current_mcp_stats_on_each_request(monkeypatch) -> None:
    class FakeCatalog:
        def list_projects(self, **kwargs: Any) -> dict[str, Any]:
            return {"items": [], "total": 6983, "page": 1, "page_size": 1}

    readings = iter([(3993, 7), (4001, 8)])

    async def fake_mcp_counts(request: Request) -> tuple[int, int]:
        return next(readings)

    monkeypatch.setattr(routes_dashboard, "_get_mcp_call_counts", fake_mcp_counts)
    client = _summary_client(monkeypatch, lambda: FakeCatalog())
    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract-summary-live")
    try:
        first = client.get("/api/dashboard/summary?date=2020-01-02")
        second = client.get("/api/dashboard/summary?date=2020-01-02")
    finally:
        FastAPICache.reset()

    assert first.status_code == second.status_code == 200
    assert first.headers["cache-control"] == "no-store, max-age=0, must-revalidate"
    assert second.json()["stats"]["mcp_total_calls"] == 4001
    assert second.json()["stats"]["mcp_dsh_calls"] == 8


def test_github_library_count_failure_logs_warning_and_returns_none(monkeypatch, caplog) -> None:
    from backend.app.services.project_catalog.query_service import (
        ProjectCatalogQueryService,
    )

    def broken_factory():
        raise RuntimeError("catalog down")

    catalog = ProjectCatalogQueryService(repository_factory=broken_factory)

    with caplog.at_level("WARNING", logger="backend.app.api.routes_dashboard"):
        result = asyncio.run(routes_dashboard._github_library_count(catalog))

    assert result is None
    assert "项目库 GitHub 收录量查询失败" in caplog.text


def test_summary_github_stat_falls_back_to_documents_when_catalog_unavailable(monkeypatch) -> None:
    def broken_factory():
        raise RuntimeError("catalog down")

    client = _summary_client(monkeypatch, broken_factory)
    # 与上一个 summary 用例同 URL 同 key：必须用独立 prefix 隔离类级共享的
    # InMemoryBackend._store，否则命中上一用例写入的缓存响应
    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract-summary-fallback")
    try:
        response = client.get("/api/dashboard/summary?date=2020-01-02")
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0, must-revalidate"
    assert response.headers["pragma"] == "no-cache"
    stats = response.json()["stats"]
    assert stats["source_counts"] == {"arxiv": 5, "github": 461, "news": 7}
    assert stats["total_documents"] == 5 + 461 + 7
    assert isinstance(stats["mcp_total_calls"], int)
    assert isinstance(stats["mcp_dsh_calls"], int)


def test_live_stats_returns_flat_counters(monkeypatch) -> None:
    class FakeCatalog:
        def list_projects(self, **kwargs: Any) -> dict[str, Any]:
            return {"items": [], "total": 6983, "page": 1, "page_size": 1}

    client = _summary_client(monkeypatch, lambda: FakeCatalog())
    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract")
    try:
        response = client.get("/api/dashboard/live-stats")
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0, must-revalidate"
    assert response.headers["pragma"] == "no-cache"
    body = response.json()
    assert body["source_counts"] == {"arxiv": 5, "github": 6983, "news": 7}
    assert body["total_documents"] == 5 + 6983 + 7
    assert body["registered_users"] == 13
    assert body["today_registered_users"] == 0
    assert body["user_count"] == 13
    assert body["today_new_documents"] == 3
    # 访问计数接真值（纯次数口径）；today_unique_visitors 复用同一口径
    assert body["today_visits"] == 7
    assert body["total_visits"] == 700
    assert body["today_unique_visitors"] == 7
    assert isinstance(body["mcp_total_calls"], int)
    assert isinstance(body["mcp_dsh_calls"], int)


# ── 默认视图快照日期回溯（Unit C）────────────────────────────────────
# 背景：代理断供两天期间今日无任何快照，看板整日空白。默认视图（不传
# date）现在向前回溯窗口内最近有快照的日期，并以 requested_date /
# resolved_date / stale 标记显式暴露；显式 date 永不回溯。


def test_resolve_default_snapshot_date_picks_latest_within_window() -> None:
    anchor = date(2026, 8, 10)
    assert (
        policy.resolve_default_snapshot_date(
            ["2026-08-07", "2026-08-09", "2026-08-04"], today=anchor
        )
        == "2026-08-09"
    )


def test_resolve_default_snapshot_date_skips_future_and_garbage() -> None:
    anchor = date(2026, 8, 10)
    assert (
        policy.resolve_default_snapshot_date(
            ["2026-08-12", "not-a-date", "2026-08-08"], today=anchor
        )
        == "2026-08-08"
    )


def test_resolve_default_snapshot_date_window_boundary() -> None:
    anchor = date(2026, 8, 10)
    # 默认窗口含今天共 7 天：08-04 在内、08-03 出窗
    assert (
        policy.resolve_default_snapshot_date(
            ["2026-08-03", "2026-08-04"], today=anchor
        )
        == "2026-08-04"
    )
    assert (
        policy.resolve_default_snapshot_date(["2026-08-03"], today=anchor) is None
    )
    assert policy.resolve_default_snapshot_date([], today=anchor) is None


def test_display_date_explicit_param_never_falls_back() -> None:
    reader = FakeRankSnapshotReader(dates=["2026-08-09"])
    service = DashboardQueryService(reader)

    resolution = service.resolve_display_snapshot_date("2026-08-01", "daily", "github")

    assert resolution == {
        "requested_date": "2026-08-01",
        "resolved_date": "2026-08-01",
        "stale": False,
    }
    assert reader.date_calls == []


def test_display_date_default_uses_today_when_snapshots_exist() -> None:
    today = policy.today_local().isoformat()
    reader = FakeRankSnapshotReader(dates=[today, "2026-08-01"])
    service = DashboardQueryService(reader)

    resolution = service.resolve_display_snapshot_date(None, "daily", None)

    assert resolution == {
        "requested_date": today,
        "resolved_date": today,
        "stale": False,
    }


def test_display_date_default_falls_back_and_marks_stale() -> None:
    today = policy.today_local()
    yesterday = (today - timedelta(days=1)).isoformat()
    reader = FakeRankSnapshotReader(dates=[yesterday])
    service = DashboardQueryService(reader)

    resolution = service.resolve_display_snapshot_date(None, "daily", "github")

    assert resolution == {
        "requested_date": today.isoformat(),
        "resolved_date": yesterday,
        "stale": True,
    }
    # 回溯查询按 source+period 口径且有界
    assert reader.date_calls == [
        (policy.DEFAULT_SNAPSHOT_LOOKBACK_DAYS, "github", "daily")
    ]


def test_display_date_default_without_any_snapshot_stays_on_today() -> None:
    today = policy.today_local().isoformat()
    reader = FakeRankSnapshotReader(dates=[])
    service = DashboardQueryService(reader)

    resolution = service.resolve_display_snapshot_date(None, "daily", None)

    assert resolution == {
        "requested_date": today,
        "resolved_date": today,
        "stale": False,
    }


def _top_client(
    reader: FakeRankSnapshotReader,
    github_hot: FakeGitHubHotReader | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(routes_dashboard.router, prefix="/api")
    app.dependency_overrides[get_rank_snapshot_repository] = lambda: reader
    app.dependency_overrides[get_github_hot_board_reader] = (
        lambda: github_hot if github_hot is not None else FakeGitHubHotReader()
    )
    return TestClient(app)


# ── github 日榜切换 v5 热度指标（今日暴涨口径）──────────────────────────
# 首页 github 榜原镜像 GitHub trending 快照（rank_snapshots 的
# github_trending_daily 渠道）；现改读项目库日度热度指标（hot_score v5
# 排序的正增长仓库）。日期回溯与历史可用日期同样以指标表为准；
# 未注入热度读取的调用方（MCP inbound）保持 trending 快照口径。


def test_top_route_default_view_falls_back_to_latest_snapshot_date() -> None:
    today = policy.today_local()
    fallback = (today - timedelta(days=2)).isoformat()
    reader = FakeRankSnapshotReader()
    github_hot = FakeGitHubHotReader(
        {fallback: [_github_metric_row(metric_date=fallback)]},
        dates=[fallback],
    )

    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract-top-fallback")
    try:
        response = _top_client(reader, github_hot).get(
            "/api/dashboard/top?source=github&limit=5"
        )
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["items"]] == ["owner/repo"]
    assert payload["snapshot_date"] == fallback
    assert payload["requested_date"] == today.isoformat()
    assert payload["resolved_date"] == fallback
    assert payload["stale"] is True
    assert payload["is_finalized"] is True
    assert payload["is_embargoed"] is False
    # 日期回溯与榜单读取都走 v5 指标，不再触碰 trending 快照
    assert github_hot.date_calls == [policy.DEFAULT_SNAPSHOT_LOOKBACK_DAYS]
    assert github_hot.hot_calls == [(fallback, 500)]
    assert reader.date_calls == []
    assert reader.document_calls == []


def test_top_route_github_metrics_doc_shape_is_wire_compatible() -> None:
    today = policy.today_local().isoformat()
    reader = FakeRankSnapshotReader()
    github_hot = FakeGitHubHotReader(
        {
            today: [
                _github_metric_row(),
                _github_metric_row(
                    repo_id="owner/other",
                    full_name="owner/other",
                    url="https://github.com/owner/other",
                    daily_star_growth=88,
                    hot_score=91.3,
                    topics_json="not-json",
                ),
            ]
        },
        dates=[today],
    )

    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract-top-v5shape")
    try:
        response = _top_client(reader, github_hot).get(
            "/api/dashboard/top?source=github&limit=5"
        )
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    first = items[0]
    # 看板渲染所需的核心字段：标题/链接/来源/星数/语言/摘要
    assert first["source"] == "github"
    assert first["title"] == "owner/repo"
    assert first["url"] == "https://github.com/owner/repo"
    assert first["stars"] == 12000
    assert first["language"] == "Python"
    assert first["summary"] == "LLM agent framework"
    assert first["tags"] == ["llm", "agents"]
    # 既有语义字段：raw_score 兜底取日增，score 承载 hot_score，名次连续
    assert first["raw_score"] == 514.0
    assert first["score"] == 96.5
    assert [item["rank_in_period"] for item in items] == [1, 2]
    assert first["source_channel"] == policy.GITHUB_METRICS_DAILY_CHANNEL
    # 附加透出的 v5 字段（旧前端忽略）
    assert first["daily_star_growth"] == 514
    assert first["daily_growth_source"] == "snapshot_delta"
    assert first["previous_snapshot_date"] == "2026-08-09"
    assert first["hot_score"] == 96.5
    # 反作弊打标字段（仅透出，不影响排序）
    assert first["growth_suspicion_score"] == 0.4
    assert first["growth_suspicion_signals"] == '["low_fork_follow"]'
    assert first["growth_corroborated"] is False
    # topics_json 解析失败时降级为空列表而非 500
    assert items[1]["tags"] == []


def test_top_route_github_explicit_date_is_honest() -> None:
    reader = FakeRankSnapshotReader()
    github_hot = FakeGitHubHotReader(
        {"2026-08-01": [_github_metric_row(metric_date="2026-08-01")]},
        dates=["2026-08-09"],
    )

    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract-top-v5explicit")
    try:
        response = _top_client(reader, github_hot).get(
            "/api/dashboard/top?source=github&date=2026-08-01"
        )
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    payload = response.json()
    # 显式 date 永不回溯：不查可用日期，直接按该日读指标
    assert github_hot.date_calls == []
    assert github_hot.hot_calls == [("2026-08-01", 500)]
    assert payload["requested_date"] == "2026-08-01"
    assert payload["resolved_date"] == "2026-08-01"
    assert payload["stale"] is False
    assert [item["id"] for item in payload["items"]] == ["owner/repo"]


def test_top_route_github_metricless_date_returns_honest_empty_board() -> None:
    # 指标缺失的日期返回空榜，不回退 trending 快照混排口径
    reader = FakeRankSnapshotReader(
        {
            ("2026-08-01", "github_trending_daily", "github"): [
                {"id": "legacy", "source": "github"}
            ]
        }
    )
    github_hot = FakeGitHubHotReader()

    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract-top-v5empty")
    try:
        response = _top_client(reader, github_hot).get(
            "/api/dashboard/top?source=github&date=2026-08-01"
        )
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert reader.document_calls == []


def test_top_route_github_default_view_fallback_still_respects_embargo(monkeypatch) -> None:
    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def]
            value = cls(2026, 8, 10, 10, 0, 0)  # 10:00 < FINALIZE_HOUR(15)
            return value.replace(tzinfo=tz) if tz else value

    monkeypatch.setattr(policy, "datetime", _FrozenDateTime)
    # today=2026-08-10 无指标 → 回溯到昨天 08-09 → 昨天仍在静默期 → 拦截
    reader = FakeRankSnapshotReader()
    github_hot = FakeGitHubHotReader(dates=["2026-08-09", "2026-08-08"])

    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract-top-v5embargo")
    try:
        response = _top_client(reader, github_hot).get(
            "/api/dashboard/top?source=github"
        )
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["requested_date"] == "2026-08-10"
    assert payload["resolved_date"] == "2026-08-09"
    assert payload["stale"] is True
    assert payload["is_embargoed"] is True
    # 静默期拦截先于榜单查询，未解禁数据不外泄
    assert github_hot.hot_calls == []


def test_github_service_without_reader_keeps_trending_snapshot_reads() -> None:
    # MCP inbound 等未注入热度读取的调用方：github 日榜保持 trending 快照口径
    docs = [{"id": "repo", "source": "github"}]
    reader = FakeRankSnapshotReader(
        {("2026-08-01", "github_trending_daily", "github"): docs}
    )
    service = DashboardQueryService(reader)

    result = service.get_docs_for_date("2026-08-01", "daily", "github", 500)

    assert result == docs
    assert reader.document_calls == [
        ("2026-08-01", "github_trending_daily", "github", 500)
    ]


def test_github_service_metric_dates_drive_default_resolution_with_reader() -> None:
    # 回溯窗口锚定真实今天（today-6..today），硬编码日期会随时间漂出窗口
    today = policy.today_local()
    recent = (today - timedelta(days=1)).isoformat()
    older = (today - timedelta(days=2)).isoformat()
    github_hot = FakeGitHubHotReader(dates=[recent])
    reader = FakeRankSnapshotReader(dates=[older])
    service = DashboardQueryService(reader, github_hot)

    resolution = service.resolve_display_snapshot_date(None, "daily", "github")

    assert resolution["resolved_date"] == recent
    assert github_hot.date_calls == [policy.DEFAULT_SNAPSHOT_LOOKBACK_DAYS]
    assert reader.date_calls == []


def test_snapshot_dates_route_github_uses_metric_dates() -> None:
    reader = FakeRankSnapshotReader(dates=["2026-08-05"])
    github_hot = FakeGitHubHotReader(dates=["2026-08-10", "2026-08-08"])

    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract-dates-github")
    try:
        response = _top_client(reader, github_hot).get(
            "/api/dashboard/snapshot-dates?source=github&limit=5"
        )
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    payload = response.json()
    assert payload["dates"] == ["2026-08-10", "2026-08-08"]
    assert payload["source"] == "github"
    assert github_hot.date_calls == [5]
    assert reader.date_calls == []


def test_snapshot_dates_route_other_sources_keep_snapshot_reads() -> None:
    reader = FakeRankSnapshotReader(dates=["2026-08-07"])
    github_hot = FakeGitHubHotReader(dates=["2026-08-10"])

    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract-dates-arxiv")
    try:
        response = _top_client(reader, github_hot).get(
            "/api/dashboard/snapshot-dates?source=arxiv&limit=3"
        )
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    assert response.json()["dates"] == ["2026-08-07"]
    assert reader.date_calls == [(3, "arxiv", "daily")]
    assert github_hot.date_calls == []


def test_github_metric_to_doc_defaults_and_rank() -> None:
    doc = policy.github_metric_to_doc(
        {"repo_id": "a/b", "full_name": "a/b", "metric_date": "2026-08-10"},
        rank=7,
    )

    assert doc["id"] == "a/b"
    assert doc["source"] == "github"
    assert doc["title"] == "a/b"
    assert doc["summary"] == ""
    assert doc["stars"] == 0
    assert doc["language"] == ""
    assert doc["tags"] == []
    assert doc["raw_score"] == 0.0
    assert doc["score"] == 0.0
    assert doc["rank_in_period"] == 7
    assert doc["source_channel"] == policy.GITHUB_METRICS_DAILY_CHANNEL
    assert doc["snapshot_date"] == "2026-08-10"
    assert doc["published_at"] is None
    assert doc["growth_suspicion_score"] == 0.0
    assert doc["growth_suspicion_signals"] == "[]"
    assert doc["growth_corroborated"] is False


def test_github_service_weekly_keeps_snapshot_channel_even_with_reader() -> None:
    # v5 热度只有日榜口径：周/月榜即使有注入也仍走 trending 快照
    docs = [{"id": "repo", "source": "github"}]
    reader = FakeRankSnapshotReader(
        {("2026-08-01", "github_trending_weekly", "github"): docs}
    )
    github_hot = FakeGitHubHotReader()
    service = DashboardQueryService(reader, github_hot)

    result = service.get_docs_for_date("2026-08-01", "weekly", "github", 500)

    assert result == docs
    assert reader.document_calls == [
        ("2026-08-01", "github_trending_weekly", "github", 500)
    ]
    assert github_hot.hot_calls == []


def test_summary_mix_view_github_items_come_from_metrics(monkeypatch) -> None:
    date = "2020-01-02"
    reader = FakeRankSnapshotReader(
        {
            (date, "huggingface_daily_html", "arxiv"): [
                {
                    "id": "paper-1",
                    "source": "arxiv",
                    "title": "A paper",
                    "url": "https://example.test/paper",
                }
            ]
        }
    )
    github_hot = FakeGitHubHotReader({date: [_github_metric_row(metric_date=date)]})

    class FakeCatalog:
        def list_projects(self, **kwargs: Any) -> dict[str, Any]:
            return {"items": [], "total": 0, "page": 1, "page_size": 1}

    client = _summary_client(
        monkeypatch, lambda: FakeCatalog(), reader=reader, github_hot=github_hot
    )
    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract-summary-mix")
    try:
        response = client.get(f"/api/dashboard/summary?date={date}")
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    top_list = response.json()["top_list"]
    sources = {(item["id"], item["source"]) for item in top_list}
    assert ("owner/repo", "github") in sources
    assert ("paper-1", "arxiv") in sources
    github_item = next(item for item in top_list if item["source"] == "github")
    assert github_item["daily_star_growth"] == 514
    assert github_item["source_channel"] == policy.GITHUB_METRICS_DAILY_CHANNEL
    # 混合视图下 github 读指标表，其他来源仍读快照
    assert github_hot.hot_calls == [(date, 500)]
    assert (date, "huggingface_daily_html", "arxiv", 500) in reader.document_calls
    assert all(call[1] != "github_trending_daily" for call in reader.document_calls)


def test_top_route_default_view_fallback_still_respects_embargo(monkeypatch) -> None:
    class _FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[no-untyped-def]
            value = cls(2026, 8, 10, 10, 0, 0)  # 10:00 < FINALIZE_HOUR(15)
            return value.replace(tzinfo=tz) if tz else value

    monkeypatch.setattr(policy, "datetime", _FrozenDateTime)
    # today=2026-08-10 无快照 → 回溯到昨天 08-09 → 昨天仍在静默期 → 拦截
    reader = FakeRankSnapshotReader(dates=["2026-08-09", "2026-08-08"])

    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract-top-embargo")
    try:
        response = _top_client(reader).get("/api/dashboard/top")
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == []
    assert payload["requested_date"] == "2026-08-10"
    assert payload["resolved_date"] == "2026-08-09"
    assert payload["stale"] is True
    assert payload["is_embargoed"] is True
    # 静默期拦截先于文档查询，未解禁数据不外泄
    assert reader.document_calls == []


def test_radar_route_default_view_carries_resolution_markers() -> None:
    today = policy.today_local()
    fallback = (today - timedelta(days=2)).isoformat()
    reader = FakeRankSnapshotReader(dates=[fallback])

    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract-radar-fallback")
    try:
        response = _top_client(reader).get("/api/dashboard/radar")
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    payload = response.json()
    assert payload["requested_date"] == today.isoformat()
    assert payload["resolved_date"] == fallback
    assert payload["stale"] is True
    assert payload["doc_count"] == 0
    assert reader.date_calls == [
        (policy.DEFAULT_SNAPSHOT_LOOKBACK_DAYS, None, "daily")
    ]


def test_summary_route_default_view_carries_resolution_markers(monkeypatch) -> None:
    today = policy.today_local()
    fallback = (today - timedelta(days=2)).isoformat()
    reader = FakeRankSnapshotReader(dates=[fallback])

    class FakeCatalog:
        def list_projects(self, **kwargs: Any) -> dict[str, Any]:
            return {"items": [], "total": 0, "page": 1, "page_size": 1}

    client = _summary_client(monkeypatch, lambda: FakeCatalog(), reader=reader)
    FastAPICache.init(InMemoryBackend(), prefix="dashboard-contract-summary-fb-mark")
    try:
        response = client.get("/api/dashboard/summary")
    finally:
        FastAPICache.reset()

    assert response.status_code == 200
    payload = response.json()
    assert payload["requested_date"] == today.isoformat()
    assert payload["resolved_date"] == fallback
    assert payload["snapshot_date"] == fallback
    assert payload["stale"] is True
