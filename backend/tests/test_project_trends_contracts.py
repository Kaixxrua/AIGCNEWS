from __future__ import annotations

import unittest
from datetime import date
from typing import Any
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_github_projects
from backend.app.api.dependencies import get_project_trends_service
from backend.app.services.project_catalog.trends_service import (
    RANK_DEPTH,
    TRENDS_MAX_REPOS,
    ProjectTrendsService,
)


def _trends_client(service: Any) -> TestClient:
    app = FastAPI()
    app.include_router(routes_github_projects.router, prefix="/api")
    app.dependency_overrides[get_project_trends_service] = lambda: service
    return TestClient(app)


def _fake_service(result: dict[str, Any] | None = None) -> AsyncMock:
    service = AsyncMock(spec=ProjectTrendsService)
    service.trends.return_value = result or {"metric_date": "2026-10-02", "days": 14, "items": {}}
    return service


def test_trends_route_parses_repos_and_forwards_window() -> None:
    service = _fake_service({
        "metric_date": "2026-10-02",
        "previous_date": "2026-10-01",
        "days": 14,
        "items": {
            "acme/alpha": {
                "points": [{"date": "2026-10-02", "stars": 1200, "gain": 42}],
                "previous_rank": 3,
            },
            "acme/beta": {"points": [], "previous_rank": None},
        },
    })
    response = _trends_client(service).get(
        "/api/projects/github/trends",
        params={"repos": " acme/alpha, acme/beta ,acme/alpha,", "ranks": "true"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=120"
    service.trends.assert_awaited_once_with(["acme/alpha", "acme/beta"], days=14, with_ranks=True)
    assert response.json() == {
        "metric_date": "2026-10-02",
        "previous_date": "2026-10-01",
        "days": 14,
        "items": {
            "acme/alpha": {
                "points": [{"date": "2026-10-02", "stars": 1200, "gain": 42}],
                "previous_rank": 3,
            },
            "acme/beta": {"points": [], "previous_rank": None},
        },
    }


def test_trends_route_defaults_to_two_weeks_without_ranks() -> None:
    service = _fake_service()
    response = _trends_client(service).get("/api/projects/github/trends?repos=acme/alpha&days=30")

    assert response.status_code == 200
    service.trends.assert_awaited_once_with(["acme/alpha"], days=30, with_ranks=False)
    assert response.json()["previous_date"] is None


def test_trends_route_rejects_bad_repo_lists_and_windows() -> None:
    service = _fake_service()
    client = _trends_client(service)
    too_many = ",".join(f"acme/repo-{index}" for index in range(TRENDS_MAX_REPOS + 1))

    for query in (
        "",
        "?repos=,,,",
        "?repos=acme",
        "?repos=acme/alpha,../etc/passwd",
        "?repos=acme/alpha%20beta",
        "?repos=acme/alpha/extra",
        f"?repos={too_many}",
        "?repos=acme/alpha&days=6",
        "?repos=acme/alpha&days=31",
    ):
        assert client.get(f"/api/projects/github/trends{query}").status_code == 422, query
    service.trends.assert_not_awaited()


def test_trends_route_accepts_a_full_page_of_repos() -> None:
    service = _fake_service()
    full_page = ",".join(f"acme/repo-{index}" for index in range(TRENDS_MAX_REPOS))

    response = _trends_client(service).get(f"/api/projects/github/trends?repos={full_page}")

    assert response.status_code == 200
    assert len(service.trends.await_args.args[0]) == TRENDS_MAX_REPOS


class FakeTrendRepository:
    def __init__(self, latest: str | None, rows: list[dict[str, Any]]) -> None:
        self.latest = latest
        self.rows = rows
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def latest_metric_date(self, *, start: str, end: str) -> str | None:
        self.calls.append(("latest", {"start": start, "end": end}))
        return self.latest

    def daily_points(self, repo_ids: list[str], *, start: str, end: str) -> list[dict[str, Any]]:
        self.calls.append(("points", {"repo_ids": list(repo_ids), "start": start, "end": end}))
        return self.rows


class FakeCatalogRepository:
    def __init__(self, ranked: list[str]) -> None:
        self.ranked = ranked
        self.calls: list[dict[str, Any]] = []

    def list_github_hot_for_date(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls.append(kwargs)
        return [{"repo_id": repo_id} for repo_id in self.ranked]


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class ProjectTrendsServiceTests(unittest.IsolatedAsyncioTestCase):
    def _service(
        self, trend: FakeTrendRepository, catalog: FakeCatalogRepository | None = None,
        *, today: date = date(2026, 10, 2), clock: FakeClock | None = None,
    ) -> ProjectTrendsService:
        return ProjectTrendsService(
            lambda: trend,
            lambda: catalog or FakeCatalogRepository([]),
            today=lambda: today,
            clock=clock or FakeClock(),
        )

    async def test_window_ends_on_the_latest_metric_date_and_keeps_missing_gains_empty(self) -> None:
        trend = FakeTrendRepository("2026-10-01", [
            {"repo_id": "acme/alpha", "metric_date": date(2026, 9, 30), "stars": 1100,
             "daily_star_growth": 0, "daily_growth_available": False},
            {"repo_id": "acme/alpha", "metric_date": date(2026, 10, 1), "stars": 1158,
             "daily_star_growth": 58, "daily_growth_available": True},
            {"repo_id": "acme/other", "metric_date": date(2026, 10, 1), "stars": 9,
             "daily_star_growth": 1, "daily_growth_available": True},
        ])

        result = await self._service(trend).trends(["acme/alpha", "acme/beta"], days=14, with_ranks=False)

        assert trend.calls == [
            ("latest", {"start": "2026-10-01", "end": "2026-10-02"}),
            ("points", {"repo_ids": ["acme/alpha", "acme/beta"], "start": "2026-09-18", "end": "2026-10-01"}),
        ]
        assert result == {
            "metric_date": "2026-10-01",
            "days": 14,
            "items": {
                "acme/alpha": {"points": [
                    {"date": "2026-09-30", "stars": 1100, "gain": None},
                    {"date": "2026-10-01", "stars": 1158, "gain": 58},
                ]},
                "acme/beta": {"points": []},
            },
        }

    async def test_window_falls_back_to_today_without_recent_metrics(self) -> None:
        trend = FakeTrendRepository(None, [])

        result = await self._service(trend).trends(["acme/alpha"], days=7, with_ranks=False)

        assert result["metric_date"] == "2026-10-02"
        assert trend.calls[1] == (
            "points", {"repo_ids": ["acme/alpha"], "start": "2026-09-26", "end": "2026-10-02"},
        )

    async def test_previous_ranks_come_from_the_day_before_on_the_public_hot_list(self) -> None:
        trend = FakeTrendRepository("2026-10-02", [])
        catalog = FakeCatalogRepository(["acme/beta", "acme/alpha", "acme/beta", "", "acme/gamma"])

        result = await self._service(trend, catalog).trends(
            ["acme/alpha", "acme/gamma", "acme/new"], days=14, with_ranks=True,
        )

        assert catalog.calls == [{
            "metric_date": "2026-10-01", "limit": RANK_DEPTH, "min_stars": 500, "enriched_only": True,
        }]
        assert result["previous_date"] == "2026-10-01"
        assert {repo_id: item["previous_rank"] for repo_id, item in result["items"].items()} == {
            "acme/alpha": 2, "acme/gamma": 3, "acme/new": None,
        }

    async def test_previous_ranks_are_cached_per_day_for_ten_minutes(self) -> None:
        trend = FakeTrendRepository("2026-10-02", [])
        catalog = FakeCatalogRepository(["acme/alpha"])
        clock = FakeClock()
        service = self._service(trend, catalog, clock=clock)

        await service.trends(["acme/alpha"], days=14, with_ranks=True)
        clock.now += 599
        await service.trends(["acme/alpha"], days=14, with_ranks=True)
        assert len(catalog.calls) == 1

        clock.now += 2
        await service.trends(["acme/alpha"], days=14, with_ranks=True)
        assert len(catalog.calls) == 2

        trend.latest = "2026-10-03"
        await service.trends(["acme/alpha"], days=14, with_ranks=True)
        assert [call["metric_date"] for call in catalog.calls] == ["2026-10-01", "2026-10-01", "2026-10-02"]

    async def test_ranks_are_skipped_unless_asked(self) -> None:
        catalog = FakeCatalogRepository(["acme/alpha"])

        result = await self._service(FakeTrendRepository("2026-10-02", []), catalog).trends(
            ["acme/alpha"], days=14, with_ranks=False,
        )

        assert catalog.calls == []
        assert "previous_date" not in result
        assert "previous_rank" not in result["items"]["acme/alpha"]
