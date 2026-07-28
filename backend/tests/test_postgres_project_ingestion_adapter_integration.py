from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from psycopg_pool import ConnectionPool

    from backend.app.core.postgres_database import PostgresDatabaseLifecycle
    from backend.app.core.postgres_migrations import PostgresMigrationRunner
    from backend.app.repositories.postgres_project_ingestion_repository import (
        PostgresGitHubProjectIngestionRepository,
    )
finally:
    os.chdir(_IMPORT_CWD)


def _test_dsn() -> str:
    dsn = os.environ.get("TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is required for PostgreSQL integration tests")
    database = str(conninfo_to_dict(dsn).get("dbname") or "")
    if "test" not in database.lower():
        pytest.skip("TEST_POSTGRES_DSN dbname must contain 'test'")
    return dsn


@pytest.fixture(scope="module")
def postgres_ingestion() -> Iterator[tuple[Any, Any]]:
    dsn = _test_dsn()
    schema = f"project_ingestion_it_{uuid.uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{schema}"')
    scoped_dsn = make_conninfo(dsn, options=f"-c search_path={schema}")
    database = PostgresDatabaseLifecycle(
        lambda: ConnectionPool(
            conninfo=scoped_dsn,
            min_size=1,
            max_size=4,
            timeout=10,
            kwargs={"autocommit": False, "row_factory": psycopg.rows.dict_row},
            open=False,
        )
    )
    try:
        PostgresMigrationRunner(database).apply()
        yield PostgresGitHubProjectIngestionRepository(database), database
    finally:
        database.close()
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def test_candidate_alias_availability_and_snapshot_contract(
    postgres_ingestion: tuple[Any, Any],
) -> None:
    repository, database = postgres_ingestion
    repository.upsert_github_repo_candidate(
        {
            "repo_id": "101",
            "full_name": "acme/alpha",
            "title": "Alpha",
            "stars": 700,
            "forks": 20,
            "watchers": 30,
            "created_at": "2026-01-01T00:00:00+00:00",
            "pushed_at": "2026-07-01T00:00:00+00:00",
            "first_seen_at": "2026-07-01T00:00:00+00:00",
            "last_seen_at": "2026-07-01T00:00:00+00:00",
            "last_snapshot_at": "2026-07-01T00:00:00+00:00",
        }
    )
    assert (
        repository.ensure_github_repo_candidate(
            {"repo_id": "acme/alpha", "full_name": "ACME/ALPHA", "stars": 1}
        )
        == "acme/alpha"
    )
    repository.upsert_github_repo_candidate(
        {
            "repo_id": "acme/alpha",
            "full_name": "acme/alpha",
            "stars": 650,
            "description": "kept",
        }
    )

    assert (
        repository.record_github_repo_not_found("ACME/ALPHA", checked_at="2026-07-02")
        is False
    )
    assert (
        repository.record_github_repo_not_found("acme/alpha", checked_at="2026-07-03")
        is True
    )
    assert (
        repository.record_github_repo_not_found("missing/repo", checked_at="2026-07-03")
        is False
    )
    assert (
        repository.mark_github_repo_available("Acme/Alpha", checked_at="2026-07-04")
        is True
    )

    repository.insert_github_repo_snapshot(
        {
            "repo_id": "acme/alpha",
            "snapshot_date": "2026-07-01",
            "captured_at": "2026-07-01T01:00:00+00:00",
            "stars": 700,
            "forks": 99,
            "watchers": 88,
            "community_metrics_complete": False,
        }
    )
    repository.insert_github_repo_snapshot(
        {
            "repo_id": "acme/alpha",
            "snapshot_date": "2026-07-01",
            "captured_at": "2026-07-01T02:00:00+00:00",
            "stars": 710,
            "forks": 21,
            "watchers": 31,
            "community_metrics_complete": True,
        }
    )

    with database.transaction() as connection:
        candidate = connection.execute(
            "SELECT * FROM github_repo_candidates WHERE repo_id='acme/alpha'"
        ).fetchone()
        alias = connection.execute(
            "SELECT * FROM github_repo_aliases WHERE alias_repo_id='101'"
        ).fetchone()
        snapshot = connection.execute(
            "SELECT * FROM github_repo_snapshots WHERE repo_id='acme/alpha'"
        ).fetchone()
    assert candidate["stars"] == 700
    assert candidate["description"] == "kept"
    assert candidate["availability_status"] == "active"
    assert candidate["not_found_count"] == 0
    assert alias["canonical_repo_id"] == "acme/alpha"
    assert snapshot["stars"] == 710
    assert snapshot["forks"] == 21
    assert snapshot["watchers"] == 31
    assert snapshot["community_metrics_complete"] is True
    assert repository.get_github_snapshot_count() == 1


def test_trending_metric_inputs_upsert_status_and_hot_reads(
    postgres_ingestion: tuple[Any, Any],
) -> None:
    repository, database = postgres_ingestion
    repository.insert_github_repo_snapshot(
        {
            "repo_id": "acme/alpha",
            "snapshot_date": "2026-07-27",
            "captured_at": "2026-07-27T12:00:00+00:00",
            "stars": 710,
            "forks": 21,
            "watchers": 31,
            "community_metrics_complete": True,
        }
    )
    repository.insert_github_repo_snapshot(
        {
            "repo_id": "acme/alpha",
            "snapshot_date": "2026-07-28",
            "captured_at": "2026-07-28T12:00:00+00:00",
            "stars": 760,
            "forks": 25,
            "watchers": 35,
            "community_metrics_complete": True,
            "open_issues": 5,
        }
    )
    assert (
        repository.upsert_github_trending_hit(
            {
                "repo_id": "acme/alpha",
                "full_name": "acme/alpha",
                "period": "daily",
                "observed_date": "2026-07-28",
                "rank": 5,
                "period_star_growth": 45,
                "captured_at": "2026-07-28T11:00:00+00:00",
            }
        )
        == "acme/alpha"
    )
    repository.upsert_github_trending_hit(
        {
            "repo_id": "acme/alpha",
            "full_name": "acme/alpha",
            "period": "daily",
            "observed_date": "2026-07-28",
            "rank": 2,
            "period_star_growth": 50,
            "captured_at": "2026-07-28T12:00:00+00:00",
        }
    )

    assert (
        repository.upsert_github_daily_metrics(
            [
                {
                    "repo_id": "acme/alpha",
                    "metric_date": "2026-07-27",
                    "stars": 710,
                    "daily_star_growth": 10,
                    "daily_growth_available": True,
                    "daily_growth_source": "snapshot_delta",
                }
            ]
        )
        == 1
    )
    inputs = repository.get_github_daily_metric_inputs(
        metric_date="2026-07-28",
        previous_date="2026-07-27",
        baseline_start_date="2026-07-21",
        repo_ids=["acme/alpha"],
    )
    assert len(inputs) == 1
    assert inputs[0]["previous_stars"] == 710
    assert inputs[0]["trending_daily_star_growth"] == 50
    assert inputs[0]["baseline_sample_count"] == 1

    metric = dict(inputs[0])
    metric.update(
        daily_star_growth=50,
        daily_fork_growth=4,
        daily_watcher_growth=4,
        daily_growth_available=True,
        daily_growth_source="snapshot_delta",
        hot_score=9.5,
    )
    assert repository.upsert_github_daily_metrics([metric]) == 1
    metric["hot_score"] = 10.5
    assert repository.upsert_github_daily_metrics([metric]) == 1

    targets = repository.list_github_project_metric_targets(min_stars=500)
    assert [item["repo_id"] for item in targets] == ["acme/alpha"]
    status = repository.get_github_metric_refresh_status(metric_date="2026-07-28")
    assert (
        status["target_count"]
        == status["snapshot_count"]
        == status["metric_count"]
        == 1
    )
    assert status["oldest_captured_at"] == "2026-07-28T12:00:00+00:00"
    hot = repository.get_github_hot_repos("daily", limit=10)
    assert [item["repo_id"] for item in hot] == ["acme/alpha"]
    assert hot[0]["growth"] == 50
    assert hot[0]["trending_rank"] == 2

    with database.transaction() as connection:
        stored = connection.execute(
            "SELECT * FROM github_repo_daily_metrics WHERE repo_id='acme/alpha' AND metric_date='2026-07-28'"
        ).fetchone()
    assert stored["hot_score"] == 10.5
    assert stored["daily_growth_available"] is True
