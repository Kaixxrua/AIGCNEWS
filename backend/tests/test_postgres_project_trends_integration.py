from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterator

import pytest

from backend.tests.postgres_test_safety import postgres_test_sandbox

# Import application settings away from the repository root so pydantic cannot
# discover a developer or production-like .env file during this opt-in test.
_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")

    from backend.app.repositories.postgres_github_project_trends import (
        PostgresGitHubProjectTrendRepository,
    )
    from backend.app.repositories.postgres_project_catalog import (
        PostgresProjectCatalogRepository,
    )
    from backend.app.services.project_catalog.trends_service import ProjectTrendsService
finally:
    os.chdir(_IMPORT_CWD)

DAY = date(2026, 10, 2)

# (repo_id, days before DAY, stars, daily gain, gain trustworthy, hot score)
METRICS = [
    ("acme/alpha", 7, 900, 3, True, 20.0),
    ("acme/alpha", 2, 1000, 10, True, 50.0),
    ("acme/alpha", 1, 1030, 30, True, 60.0),
    ("acme/alpha", 0, 1100, 70, True, 95.0),
    ("acme/beta", 1, 800, 40, True, 90.0),
    ("acme/beta", 0, 812, 12, True, 70.0),
    ("acme/gamma", 3, 590, 0, False, 0.0),
    ("acme/gamma", 2, 600, 5, True, 80.0),
    ("acme/gamma", 1, 620, 20, True, 40.0),
    # Hotter than everyone yesterday, but never enriched: not on the public list.
    ("acme/draft", 1, 5000, 500, True, 99.0),
    # Hot yesterday but since taken down: the hot list only ranks reachable repositories.
    ("acme/gone", 1, 700, 50, True, 85.0),
]


@pytest.fixture(scope="module")
def database() -> Iterator[Any]:
    with postgres_test_sandbox() as sandbox:
        database = sandbox.database
        with database.transaction() as connection:
            for repo_id in ("acme/alpha", "acme/beta", "acme/gamma", "acme/draft", "acme/gone"):
                connection.execute(
                    """
                    INSERT INTO github_repo_candidates (
                        repo_id, full_name, title, url, description, language, topics_json,
                        created_at, pushed_at, stars, forks, watchers, source_channels,
                        first_seen_at, last_seen_at, last_snapshot_at
                    ) VALUES (%s, %s, %s, %s, 'fixture', 'Python', '[]',
                        '2025-01-01T00:00:00Z', '2026-09-30T08:00:00Z', 1000, 10, 5, 'fixture',
                        '2026-09-01T00:00:00Z', '2026-09-30T08:00:00Z', '2026-10-02T01:00:00Z')
                    """,
                    (repo_id, repo_id, repo_id.split("/")[1], f"https://github.com/{repo_id}"),
                )
            for repo_id in ("acme/alpha", "acme/beta", "acme/gamma", "acme/gone"):
                connection.execute(
                    """
                    INSERT INTO github_repo_enrichments (
                        repo_id, category_slug, category_name, subcategory_slug, subcategory_name,
                        description_zh, tags_json, confidence, source_fingerprint, prompt_version,
                        model_provider, model_name, status, enriched_at, updated_at
                    ) VALUES (%s, 'rag_knowledge', 'RAG 与知识库', 'rag_framework', 'RAG 框架',
                        '夹具', '[]', 0.9, repeat('a', 64), 'fixture-v1',
                        'fixture', 'fixture', 'succeeded', '2026-10-01T08:00:00Z', '2026-10-01T08:00:00Z')
                    """,
                    (repo_id,),
                )
            connection.execute(
                "UPDATE github_repo_candidates SET availability_status = 'not_found' WHERE repo_id = 'acme/gone'"
            )
            for repo_id, back, stars, gain, available, hot in METRICS:
                metric_date = DAY - timedelta(days=back)
                connection.execute(
                    """
                    INSERT INTO github_repo_daily_metrics (
                        repo_id, metric_date, stars, forks, watchers, open_issues,
                        previous_snapshot_date, previous_stars, daily_star_growth,
                        daily_growth_available, daily_growth_source, daily_growth_observed_at,
                        hot_score, updated_at
                    ) VALUES (%s, %s, %s, 10, 5, 1, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s, CURRENT_TIMESTAMP)
                    """,
                    (
                        repo_id, metric_date, stars, metric_date - timedelta(days=1), stars - gain, gain,
                        available, "snapshot_delta" if available else "unavailable", hot,
                    ),
                )
        yield database


def _run(database: Any, today: date, repo_ids: list[str], *, days: int = 7, ranks: bool = True) -> dict[str, Any]:
    service = ProjectTrendsService(
        lambda: PostgresGitHubProjectTrendRepository(database),
        lambda: PostgresProjectCatalogRepository(database=database),
        today=lambda: today,
    )
    return asyncio.run(service.trends(repo_ids, days=days, with_ranks=ranks))


def test_points_cover_the_window_and_leave_untrusted_gains_empty(database: Any) -> None:
    result = _run(database, DAY, ["acme/alpha", "acme/gamma", "acme/nobody"], ranks=False)

    assert result["metric_date"] == "2026-10-02"
    assert result["items"]["acme/alpha"]["points"] == [
        {"date": "2026-09-30", "stars": 1000, "gain": 10},
        {"date": "2026-10-01", "stars": 1030, "gain": 30},
        {"date": "2026-10-02", "stars": 1100, "gain": 70},
    ]
    assert result["items"]["acme/gamma"]["points"] == [
        {"date": "2026-09-29", "stars": 590, "gain": None},
        {"date": "2026-09-30", "stars": 600, "gain": 5},
        {"date": "2026-10-01", "stars": 620, "gain": 20},
    ]
    assert result["items"]["acme/nobody"] == {"points": []}


def test_previous_ranks_follow_yesterdays_public_hot_list(database: Any) -> None:
    result = _run(database, DAY, ["acme/alpha", "acme/beta", "acme/gamma", "acme/draft", "acme/gone"])

    assert result["previous_date"] == "2026-10-01"
    assert {repo_id: item["previous_rank"] for repo_id, item in result["items"].items()} == {
        "acme/beta": 1, "acme/alpha": 2, "acme/gamma": 3, "acme/draft": None, "acme/gone": None,
    }
    # Same query, same order as the dashboard's daily hot list for that day.
    hot = PostgresProjectCatalogRepository(database=database).list_github_hot_for_date(
        metric_date="2026-10-01", limit=200,
    )
    assert [row["repo_id"] for row in hot] == ["acme/beta", "acme/alpha", "acme/gamma"]


def test_window_falls_back_one_day_then_to_today(database: Any) -> None:
    next_morning = _run(database, DAY + timedelta(days=1), ["acme/alpha"], days=30)
    assert next_morning["metric_date"] == "2026-10-02"
    assert next_morning["previous_date"] == "2026-10-01"
    assert [point["date"] for point in next_morning["items"]["acme/alpha"]["points"]] == [
        "2026-09-25", "2026-09-30", "2026-10-01", "2026-10-02",
    ]

    # Nothing since: the window still ends today, and nobody has a rank on an empty day.
    stale = _run(database, DAY + timedelta(days=5), ["acme/alpha"])
    assert stale["metric_date"] == "2026-10-07"
    assert stale["previous_date"] == "2026-10-06"
    assert stale["items"]["acme/alpha"] == {
        "points": [
            {"date": "2026-10-01", "stars": 1030, "gain": 30},
            {"date": "2026-10-02", "stars": 1100, "gain": 70},
        ],
        "previous_rank": None,
    }
