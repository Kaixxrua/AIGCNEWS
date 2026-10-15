"""Reviewed date decisions must hold at the public daily-board boundary."""
import pytest
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

from backend.app.services.dashboard.query_service import DashboardQueryService
from backend.tests.test_dashboard_contracts import (
    FakeGitHubHotReader,
    FakeRankSnapshotReader,
    _github_metric_row,
    _top_client,
)


@pytest.fixture(autouse=True)
def isolate_in_memory_response_cache(monkeypatch):
    # InMemoryBackend shares its store across instances and parametrized cases.
    monkeypatch.setattr(InMemoryBackend, "_store", {})


@pytest.mark.parametrize("day,status", [
    *[(day, "unavailable") for day in (
        "2026-03-14", "2026-07-08", "2026-07-09", "2026-07-10",
        "2026-07-12", "2026-07-13", "2026-07-14", "2026-07-23",
        "2026-08-09", "2026-09-07", "2026-09-08", "2026-09-09",
        "2026-09-12", "2026-09-13", "2026-09-14", "2026-09-15",
    )],
    *[(day, "partial") for day in (
        "2026-07-19", "2026-07-20", "2026-07-21", "2026-08-10",
        "2026-08-18", "2026-08-26", "2026-08-27", "2026-09-10",
        "2026-09-16", "2026-10-09",
    )],
    *[(day, "available") for day in (
        "2026-07-11", "2026-08-03", "2026-08-11", "2026-10-10", "2026-10-15",
    )],
])
def test_reviewed_day_keeps_explicit_date_and_reports_quality(day, status):
    reader = FakeRankSnapshotReader()
    hot = FakeGitHubHotReader({day: [_github_metric_row(metric_date=day)]}, dates=[day])
    FastAPICache.init(InMemoryBackend(), prefix="github-quality")
    try:
        client = _top_client(reader, hot)
        response = client.get(f"/api/dashboard/top?source=github&date={day}")
        dates = client.get("/api/dashboard/snapshot-dates?source=github").json()
    finally:
        FastAPICache.reset()
    assert response.status_code == 200
    payload = response.json()
    assert payload["requested_date"] == payload["resolved_date"] == day
    assert payload["stale"] is False
    quality = payload["source_status"]["github"]["data_quality"]
    assert quality["status"] == status
    assert bool(quality["reason"]) is (status != "available")
    assert payload["source_status"]["github"]["is_disabled"] is False
    assert all("data_quality" not in value for key, value in payload["source_status"].items() if key != "github")
    assert payload["total"] == len(payload["items"]) == (0 if status == "unavailable" else 1)
    assert hot.hot_calls == ([] if status == "unavailable" else [(day, 500)])
    assert day in dates["dates"]  # quality never removes calendar navigation


def test_unavailable_github_leaves_other_sources_and_legacy_snapshots_readable():
    day = "2026-09-14"
    paper = {"id": "paper", "source": "arxiv", "title": "Paper", "url": "https://example.org/paper"}
    legacy = {"id": "legacy", "source": "github", "title": "Trending", "url": "https://example.org/repo"}
    reader = FakeRankSnapshotReader({
        (day, "huggingface_daily_html", "arxiv"): [paper],
        (day, "github_trending_daily", "github"): [legacy],
        (day, "github_trending_weekly", "github"): [legacy],
    })
    hot = FakeGitHubHotReader({day: [_github_metric_row(metric_date=day)]})
    service = DashboardQueryService(reader, hot)
    assert service.get_docs_for_date(day, "daily", "all") == [paper]
    assert service.get_docs_for_date(day, "daily", "arxiv") == [paper]
    assert service.get_docs_for_date(day, "weekly", "github") == [legacy]
    assert DashboardQueryService(reader).get_docs_for_date(day, "daily", "github") == [legacy]
    assert hot.hot_calls == []
