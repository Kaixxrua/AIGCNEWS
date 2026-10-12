from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_dashboard
from backend.app.api.dependencies import (
    get_document_repository,
    get_optional_x_watch_account_repository,
)


@pytest.fixture
def timeline(monkeypatch):
    now = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(routes_dashboard, "datetime", Clock)
    rows = []
    calls = []

    def read(source, *, since_iso, until_iso, limit, keyset_after=None, x_handles=None):
        calls.append((since_iso, until_iso, limit, x_handles))
        selected = [
            row for row in rows
            if since_iso <= row["published_at"] < until_iso
            and (x_handles is None or routes_dashboard._x_followed_account_handle(row) in x_handles)
            and (keyset_after is None or (row["published_at"], 0, row["id"]) < keyset_after)
        ]
        return sorted(selected, key=lambda row: (row["published_at"], row["id"]), reverse=True)[:limit]

    def add(count, *, hours=1, handle="openai", **extra):
        for index in range(count):
            rows.append({
                "id": f"x:{len(rows):04d}", "source": "x",
                "url": f"https://x.com/{handle}/status/{len(rows)}",
                "published_at": (now - timedelta(hours=hours, minutes=index)).isoformat(),
                **extra,
            })

    app = FastAPI()
    app.include_router(routes_dashboard.router, prefix="/api")
    app.dependency_overrides[get_document_repository] = lambda: SimpleNamespace(list_recent_by_source=read)
    app.dependency_overrides[get_optional_x_watch_account_repository] = lambda: SimpleNamespace(
        list_public_x_watch_accounts=lambda: [
            {"screen_name": "openai", "display_name": "OpenAI"},
            {"screen_name": "quiet", "display_name": "Quiet"},
        ],
    )
    with TestClient(app) as client:
        yield client, add, rows, calls


@pytest.mark.parametrize("recent", [0, 1, 19, 20, 21, 100])
def test_current_window_fills_only_when_under_twenty(timeline, recent):
    client, add, rows, calls = timeline
    add(recent)
    add(25, hours=24 * 400)  # No 72-hour or 60-day lookback ceiling.
    add(1, hours=-1)  # Future tweets never enter the current window.
    response = client.get("/api/dashboard/x/recent", params={"min_items": 20})
    assert response.status_code == 200
    data = response.json()
    expected = rows[:-1][:max(20, recent)]
    assert [item["id"] for item in data["items"]] == [row["id"] for row in expected]
    assert data["total"] == max(20, recent)
    assert data["window_extended"] is (recent < 20)
    assert data["has_more"] is False
    assert data["next_cursor"] is None
    assert len(calls) == (2 if recent < 20 else 1)


@pytest.mark.parametrize("count", [0, 7])
def test_exhausted_history_returns_available_tweets_without_continuation(timeline, count):
    client, add, _, _ = timeline
    add(count, hours=120)
    data = client.get("/api/dashboard/x/recent?min_items=20").json()
    assert data["total"] == count
    assert data["window_extended"] is bool(count)
    assert data["has_more"] is False


@pytest.mark.parametrize("params", [
    {}, {"min_items": 20, "days_back": 1},
    {"min_items": 20, "cursor": routes_dashboard._x_recent_cursor_from_doc({
        "id": "x:cursor", "published_at": "2026-10-12T11:00:00+00:00",
    })},
])
def test_default_historical_and_continuation_requests_keep_strict_windows(timeline, params):
    client, add, _, calls = timeline
    add(25, hours=120)
    data = client.get("/api/dashboard/x/recent", params=params).json()
    assert data["items"] == []
    assert data["window_extended"] is False
    assert len(calls) == 1


@pytest.mark.parametrize("mode,handles,expected", [
    ("include", " @OpenAI ", 20), ("exclude", "quiet", 20),
    ("include", "", 0), ("include", "unknown", 0),
])
def test_minimum_counts_followed_accounts_and_retweets(timeline, mode, handles, expected):
    client, add, _, calls = timeline
    add(30, handle="quiet")
    add(1)
    add(25, hours=120, handle="original", retweeted_by=" @OpenAI ")
    data = client.get("/api/dashboard/x/recent", params={
        "min_items": 20, "account_mode": mode, "account_handles": handles,
    }).json()
    assert data["total"] == expected
    assert all(item["followed_account_name"] == "OpenAI" for item in data["items"])
    assert len(data["accounts"]) == 2  # Quiet accounts remain available to follow.
    assert calls[-1][3] == (["openai"] if expected else [])


def test_backfill_respects_limit_and_query_validation(timeline):
    client, add, _, _ = timeline
    add(25, hours=120)
    data = client.get("/api/dashboard/x/recent?min_items=20&limit=5").json()
    assert data["total"] == 5
    assert data["has_more"] is False
    for query in ("min_items=-1", "min_items=21", "account_mode=invalid"):
        assert client.get(f"/api/dashboard/x/recent?{query}").status_code == 422
