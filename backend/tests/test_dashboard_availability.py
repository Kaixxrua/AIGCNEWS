from datetime import datetime

import pytest
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

from backend.app.api import routes_dashboard
from backend.app.services.dashboard import policy
from backend.tests.test_dashboard_contracts import (
    FakeGitHubHotReader,
    FakeRankSnapshotReader,
    _github_metric_row,
    _top_client,
)


def freeze(monkeypatch, instant):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(instant).astimezone(tz)

    monkeypatch.setattr(policy, "datetime", FrozenDateTime)
    monkeypatch.setattr(routes_dashboard, "datetime", FrozenDateTime)


@pytest.fixture
def client():
    snapshots = FakeRankSnapshotReader({
        ("2026-08-10", "huggingface_daily_html", "arxiv"): [
            {"id": "paper", "source": "arxiv", "title": "LLM", "raw_score": 10},
        ],
    })
    metrics = FakeGitHubHotReader({
        "2026-08-10": [_github_metric_row(metric_date="2026-08-10")],
    })
    FastAPICache.init(InMemoryBackend(), prefix="visible-drafts")
    try:
        with _top_client(snapshots, metrics) as instance:
            yield instance
    finally:
        FastAPICache.reset()


@pytest.mark.parametrize("source,close", [("github", "01"), ("arxiv", "17")])
def test_cached_board_remains_visible_across_midnight_and_source_close(monkeypatch, client, source, close):
    url = f"/api/dashboard/top?source={source}&date=2026-08-10"
    for instant, finalized in [
        ("2026-08-10T23:59:59+08:00", False),
        ("2026-08-11T00:00:00+08:00", False),
        (f"2026-08-11T{int(close) - 1:02d}:59:59+08:00", False),
        (f"2026-08-11T{close}:00:00+08:00", True),
    ]:
        freeze(monkeypatch, instant)
        response = client.get(url)
        assert response.status_code == 200
        body = response.json()
        assert len(body["items"]) == 1
        assert body["snapshot_date"] == "2026-08-10"
        assert body["is_embargoed"] is False
        assert body["is_finalized"] is finalized
        assert body["source_status"][source]["is_finalized"] is finalized
        assert 0 < int(response.headers["cache-control"].split("=")[1]) <= 60


@pytest.mark.parametrize("endpoint,field", [("summary-static", "top_list"), ("radar", "radar")])
def test_summary_and_radar_expose_yesterday_during_collection(monkeypatch, client, endpoint, field):
    freeze(monkeypatch, "2026-08-11T10:00:00+08:00")
    body = client.get(f"/api/dashboard/{endpoint}?date=2026-08-10").json()
    assert body[field]
    assert body["is_embargoed"] is False
    assert body["is_finalized"] is False
