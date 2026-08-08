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
    from backend.app.services.github_watcher_corruption_repair import (
        GitHubWatcherCorruptionRepairService,
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


def test_authoritative_watchers_can_decrease_without_stale_or_incomplete_overwrite(
    postgres_ingestion: tuple[Any, Any],
) -> None:
    repository, database = postgres_ingestion
    repository.upsert_github_repo_candidate(
        {
            "repo_id": "acme/watchers",
            "full_name": "acme/watchers",
            "stars": 400,
            "watchers": 700,
            "community_metrics_complete": True,
            "last_snapshot_at": "2026-07-28T01:00:00+00:00",
        }
    )
    repository.upsert_github_repo_candidate(
        {
            "repo_id": "acme/watchers",
            "full_name": "acme/watchers",
            "stars": 410,
            "watchers": 12,
            "community_metrics_complete": True,
            "last_snapshot_at": "2026-07-28T02:00:00+00:00",
        }
    )
    repository.upsert_github_repo_candidate(
        {
            "repo_id": "acme/watchers",
            "full_name": "acme/watchers",
            "stars": 420,
            "watchers": 0,
            "community_metrics_complete": False,
            "last_snapshot_at": "2026-07-28T03:00:00+00:00",
        }
    )
    repository.upsert_github_repo_candidate(
        {
            "repo_id": "acme/watchers",
            "full_name": "acme/watchers",
            "stars": 420,
            "watchers": 99,
            "community_metrics_complete": True,
            "last_snapshot_at": "2026-07-28T01:30:00+00:00",
        }
    )

    repository.insert_github_repo_snapshot(
        {
            "repo_id": "acme/watchers",
            "snapshot_date": "2026-07-28",
            "captured_at": "2026-07-28T01:00:00+00:00",
            "stars": 400,
            "watchers": 700,
            "community_metrics_complete": True,
        }
    )
    repository.insert_github_repo_snapshot(
        {
            "repo_id": "acme/watchers",
            "snapshot_date": "2026-07-28",
            "captured_at": "2026-07-28T02:00:00+00:00",
            "stars": 410,
            "watchers": 12,
            "community_metrics_complete": True,
        }
    )
    repository.insert_github_repo_snapshot(
        {
            "repo_id": "acme/watchers",
            "snapshot_date": "2026-07-28",
            "captured_at": "2026-07-28T03:00:00+00:00",
            "stars": 420,
            "watchers": 0,
            "community_metrics_complete": False,
        }
    )
    repository.insert_github_repo_snapshot(
        {
            "repo_id": "acme/watchers",
            "snapshot_date": "2026-07-28",
            "captured_at": "2026-07-28T01:30:00+00:00",
            "stars": 420,
            "watchers": 99,
            "community_metrics_complete": True,
        }
    )

    with database.transaction() as connection:
        candidate = connection.execute(
            "SELECT watchers FROM github_repo_candidates WHERE repo_id='acme/watchers'"
        ).fetchone()
        snapshot = connection.execute(
            "SELECT watchers,community_metrics_complete,captured_at "
            "FROM github_repo_snapshots WHERE repo_id='acme/watchers' "
            "AND snapshot_date='2026-07-28'"
        ).fetchone()
    assert candidate["watchers"] == 12
    assert snapshot["watchers"] == 12
    assert snapshot["community_metrics_complete"] is True
    assert snapshot["captured_at"] == "2026-07-28T03:00:00+00:00"


def test_complete_snapshot_upgrades_newer_incomplete_observation(
    postgres_ingestion: tuple[Any, Any],
) -> None:
    repository, database = postgres_ingestion
    repository.upsert_github_repo_candidate(
        {
            "repo_id": "acme/upgrade",
            "full_name": "acme/upgrade",
            "stars": 400,
        }
    )
    repository.insert_github_repo_snapshot(
        {
            "repo_id": "acme/upgrade",
            "snapshot_date": "2026-07-28",
            "captured_at": "2026-07-28T03:00:00+00:00",
            "stars": 400,
            "watchers": 0,
            "community_metrics_complete": False,
        }
    )
    repository.insert_github_repo_snapshot(
        {
            "repo_id": "acme/upgrade",
            "snapshot_date": "2026-07-28",
            "captured_at": "2026-07-28T02:00:00+00:00",
            "stars": 400,
            "watchers": 12,
            "community_metrics_complete": True,
        }
    )

    with database.transaction() as connection:
        snapshot = connection.execute(
            "SELECT watchers,community_metrics_complete FROM github_repo_snapshots "
            "WHERE repo_id='acme/upgrade' AND snapshot_date='2026-07-28'"
        ).fetchone()
    assert snapshot["watchers"] == 12
    assert snapshot["community_metrics_complete"] is True


def test_watcher_corruption_repair_quarantines_history_and_is_idempotent(
    postgres_ingestion: tuple[Any, Any],
) -> None:
    repository, database = postgres_ingestion
    repository.upsert_github_repo_candidate(
        {
            "repo_id": "acme/corrupted",
            "full_name": "acme/corrupted",
            "stars": 400,
            "watchers": 400,
        }
    )
    for snapshot_date, stars, forks in (
        ("2026-07-27", 690, 20),
        ("2026-07-28", 700, 25),
        ("2026-07-29", 710, 30),
    ):
        repository.insert_github_repo_snapshot(
            {
                "repo_id": "acme/corrupted",
                "snapshot_date": snapshot_date,
                "captured_at": f"{snapshot_date}T12:00:00+00:00",
                "stars": stars,
                "forks": forks,
                "watchers": stars,
                "community_metrics_complete": True,
            }
        )
    for metric_date in ("2026-07-27", "2026-07-28", "2026-07-29"):
        repository.upsert_github_daily_metrics(
            [
                {
                    "repo_id": "acme/corrupted",
                    "metric_date": metric_date,
                    "stars": 700,
                    "forks": 25,
                    "watchers": 700,
                    "daily_star_growth": 10,
                    "daily_fork_growth": 5,
                    "daily_watcher_growth": 10,
                    "daily_growth_available": True,
                    "daily_growth_source": "snapshot_delta",
                    "scale_corrected_growth_score": 80.0,
                    "growth_acceleration_score": 70.0,
                    "absolute_growth_score": 60.0,
                    "maintenance_activity_score": 50.0,
                    "community_engagement_score": 40.0,
                    "hot_score": 73.0,
                    "score_version": "daily_hot_v4",
                }
            ]
        )

    with database.transaction() as connection:
        identity = connection.execute(
            "SELECT current_database() AS database, current_schema() AS schema"
        ).fetchone()
        target_database = identity["database"]
        target_schema = identity["schema"]
    service = GitHubWatcherCorruptionRepairService(
        postgres=database,
        config=type("Config", (), {"env": "development"})(),
    )
    dry_run = service.repair(
        target_database=target_database,
        target_schema=target_schema,
        batch_size=1,
    )
    assert dry_run["applied"] is False
    assert dry_run["matched"] == 1
    applied = service.repair(
        target_database=target_database,
        target_schema=target_schema,
        batch_size=1,
        apply=True,
    )
    assert applied["snapshots_quarantined"] == 1
    second = service.repair(
        target_database=target_database,
        target_schema=target_schema,
        batch_size=1,
        after_snapshot_date=applied["next_cursor"]["snapshot_date"],
        after_repo_id=applied["next_cursor"]["repo_id"],
        apply=True,
    )
    assert second["snapshots_quarantined"] == 1

    with database.transaction() as connection:
        repaired = connection.execute(
            "SELECT snapshot_date,watchers,community_metrics_complete "
            "FROM github_repo_snapshots WHERE repo_id='acme/corrupted' "
            "ORDER BY snapshot_date"
        ).fetchall()
        metrics = connection.execute(
            "SELECT metric_date,daily_fork_growth,daily_watcher_growth,"
            "community_engagement_score,hot_score,score_version "
            "FROM github_repo_daily_metrics WHERE repo_id='acme/corrupted' "
            "ORDER BY metric_date"
        ).fetchall()
    assert repaired[0]["community_metrics_complete"] is False
    assert repaired[0]["watchers"] == 0
    assert repaired[1]["community_metrics_complete"] is False
    assert repaired[1]["watchers"] == 0
    assert repaired[2]["community_metrics_complete"] is True
    assert metrics[0]["community_engagement_score"] == 0.0
    assert metrics[1]["community_engagement_score"] == 0.0
    assert metrics[2]["community_engagement_score"] == 0.0
    assert metrics[0]["hot_score"] == 69.0
    assert metrics[0]["score_version"] == "daily_hot_v4"

    final = service.repair(
        target_database=target_database,
        target_schema=target_schema,
        batch_size=10,
        apply=True,
    )
    assert final["snapshots_quarantined"] == 1
    idempotent = service.repair(
        target_database=target_database,
        target_schema=target_schema,
        batch_size=10,
        apply=True,
    )
    assert idempotent["matched"] == 0
    assert idempotent["snapshots_quarantined"] == 0


def _delete_candidates(database: Any, *repo_ids: str) -> None:
    """清走本文件批量观测测试创建的候选行（级联删快照/别名），避免污染共享 schema。"""
    with database.transaction() as connection:
        connection.execute(
            "DELETE FROM github_repo_candidates WHERE repo_id = ANY(%s)",
            (list(repo_ids),),
        )


def test_metric_observations_batch_matches_single_row_write_semantics(
    postgres_ingestion: tuple[Any, Any],
) -> None:
    repository, database = postgres_ingestion
    try:
        repository.upsert_github_repo_candidate(
            {
                "repo_id": "acme/batch-down",
                "full_name": "acme/batch-down",
                "stars": 700,
                "last_snapshot_at": "2026-07-01T00:00:00+00:00",
            }
        )
        assert (
            repository.record_github_repo_not_found("acme/batch-down", checked_at="2026-07-29")
            is False
        )
        assert (
            repository.record_github_repo_not_found("acme/batch-down", checked_at="2026-07-29")
            is True
        )
        repository.insert_github_repo_snapshot(
            {
                "repo_id": "acme/batch-down",
                "snapshot_date": "2026-07-30",
                "captured_at": "2026-07-30T00:30:00+00:00",
                "stars": 700,
                "watchers": 40,
                "community_metrics_complete": True,
            }
        )

        written = repository.upsert_github_repo_metric_observations(
            [
                {
                    "candidate": {
                        "repo_id": "acme/batch-down",
                        "full_name": "acme/batch-down",
                        "stars": 750,
                        "forks": 5,
                        "watchers": 9,
                        "community_metrics_complete": True,
                        "source_channels": "daily_metrics",
                        "last_snapshot_at": "2026-07-30T01:00:00+00:00",
                    },
                    # 可用性恢复与单行方法一致按 LOWER(full_name) 匹配
                    "available_full_name": "ACME/BATCH-DOWN",
                    "snapshot": {
                        "repo_id": "acme/batch-down",
                        "full_name": "acme/batch-down",
                        "snapshot_date": "2026-07-30",
                        "captured_at": "2026-07-30T01:00:00+00:00",
                        "stars": 750,
                        "forks": 5,
                        "watchers": 9,
                        "community_metrics_complete": True,
                    },
                },
                {
                    "candidate": {
                        "repo_id": "acme/batch-fresh",
                        "full_name": "acme/batch-fresh",
                        "stars": 600,
                        "source_channels": "daily_metrics",
                        "last_snapshot_at": "2026-07-30T01:00:00+00:00",
                    },
                    "available_full_name": "acme/batch-fresh",
                    "snapshot": {
                        "repo_id": "acme/batch-fresh",
                        "full_name": "acme/batch-fresh",
                        "snapshot_date": "2026-07-30",
                        "captured_at": "2026-07-30T01:00:00+00:00",
                        "stars": 600,
                        "community_metrics_complete": False,
                    },
                },
            ],
            checked_at="2026-07-30T01:00:00+00:00",
        )

        assert written == 2
        with database.transaction() as connection:
            down = connection.execute(
                "SELECT availability_status,not_found_count,availability_checked_at,stars,watchers "
                "FROM github_repo_candidates WHERE repo_id='acme/batch-down'"
            ).fetchone()
            fresh = connection.execute(
                "SELECT availability_status,stars,source_channels "
                "FROM github_repo_candidates WHERE repo_id='acme/batch-fresh'"
            ).fetchone()
            snapshots = connection.execute(
                "SELECT repo_id,stars,forks,watchers,community_metrics_complete,captured_at "
                "FROM github_repo_snapshots "
                "WHERE repo_id IN ('acme/batch-down','acme/batch-fresh') ORDER BY repo_id"
            ).fetchall()
        assert down["availability_status"] == "active"
        assert down["not_found_count"] == 0
        assert down["availability_checked_at"] == "2026-07-30T01:00:00+00:00"
        assert down["stars"] == 750
        assert down["watchers"] == 9
        assert fresh["availability_status"] == "active"
        assert fresh["stars"] == 600
        assert fresh["source_channels"] == "daily_metrics"
        assert len(snapshots) == 2
        down_snapshot = next(row for row in snapshots if row["repo_id"] == "acme/batch-down")
        # 同日快照冲突合并语义与单行方法一致：GREATEST + completeness 升级
        assert down_snapshot["stars"] == 750
        assert down_snapshot["forks"] == 5
        assert down_snapshot["watchers"] == 9
        assert down_snapshot["community_metrics_complete"] is True
        assert down_snapshot["captured_at"] == "2026-07-30T01:00:00+00:00"
    finally:
        _delete_candidates(database, "acme/batch-down", "acme/batch-fresh")


def test_metric_observations_batch_failure_leaves_no_partial_state(
    postgres_ingestion: tuple[Any, Any],
) -> None:
    repository, database = postgres_ingestion
    try:
        repository.upsert_github_repo_candidate(
            {"repo_id": "acme/batch-keep", "full_name": "acme/batch-keep", "stars": 900}
        )
        assert (
            repository.record_github_repo_not_found("acme/batch-keep", checked_at="2026-07-29")
            is False
        )
        assert (
            repository.record_github_repo_not_found("acme/batch-keep", checked_at="2026-07-29")
            is True
        )

        with pytest.raises(Exception):
            repository.upsert_github_repo_metric_observations(
                [
                    {
                        "candidate": {
                            "repo_id": "acme/batch-keep",
                            "full_name": "acme/batch-keep",
                            "stars": 950,
                            "last_snapshot_at": "2026-07-30T01:00:00+00:00",
                        },
                        "available_full_name": "acme/batch-keep",
                        "snapshot": {
                            "repo_id": "acme/batch-keep",
                            "full_name": "acme/batch-keep",
                            "snapshot_date": "2026-07-30",
                            "captured_at": "2026-07-30T01:00:00+00:00",
                            "stars": 950,
                        },
                    },
                    {
                        "candidate": {
                            "repo_id": "acme/batch-bad",
                            "full_name": "acme/batch-bad",
                            "stars": 800,
                        },
                        "available_full_name": "acme/batch-bad",
                        "snapshot": {
                            "repo_id": "acme/batch-bad",
                            "full_name": "acme/batch-bad",
                            # NOT NULL 违例：触发整批回滚
                            "snapshot_date": None,
                            "captured_at": "2026-07-30T01:00:00+00:00",
                            "stars": 800,
                        },
                    },
                ],
                checked_at="2026-07-30T01:00:00+00:00",
            )

        with database.transaction() as connection:
            bad_candidate = connection.execute(
                "SELECT repo_id FROM github_repo_candidates WHERE repo_id='acme/batch-bad'"
            ).fetchone()
            keep = connection.execute(
                "SELECT availability_status,stars FROM github_repo_candidates "
                "WHERE repo_id='acme/batch-keep'"
            ).fetchone()
            snapshots = connection.execute(
                "SELECT COUNT(*) AS cnt FROM github_repo_snapshots "
                "WHERE repo_id IN ('acme/batch-keep','acme/batch-bad')"
            ).fetchone()
        # 候选 upsert、可用性恢复、快照插入全部随事务回滚
        assert bad_candidate is None
        assert keep["availability_status"] == "not_found"
        assert keep["stars"] == 900
        assert snapshots["cnt"] == 0
    finally:
        _delete_candidates(database, "acme/batch-keep", "acme/batch-bad")


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
