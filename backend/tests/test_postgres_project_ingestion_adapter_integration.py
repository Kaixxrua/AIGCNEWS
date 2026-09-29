from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from backend.tests.postgres_test_safety import postgres_test_sandbox

_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")

    from backend.app.repositories.postgres_project_ingestion_repository import (
        PostgresGitHubProjectIngestionRepository,
    )
    from backend.app.services.github_watcher_corruption_repair import (
        GitHubWatcherCorruptionRepairService,
    )
finally:
    os.chdir(_IMPORT_CWD)


@pytest.fixture(scope="module")
def postgres_ingestion() -> Iterator[tuple[Any, Any]]:
    with postgres_test_sandbox() as sandbox:
        database = sandbox.database
        yield PostgresGitHubProjectIngestionRepository(database), database


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
        repository.ensure_github_repo_candidate({"repo_id": "acme/alpha", "full_name": "ACME/ALPHA", "stars": 1})
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

    assert repository.record_github_repo_not_found("ACME/ALPHA", checked_at="2026-07-02") is False
    assert repository.record_github_repo_not_found("acme/alpha", checked_at="2026-07-03") is True
    assert repository.record_github_repo_not_found("missing/repo", checked_at="2026-07-03") is False
    assert repository.mark_github_repo_available("Acme/Alpha", checked_at="2026-07-04") is True

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
        candidate = connection.execute("SELECT * FROM github_repo_candidates WHERE repo_id='acme/alpha'").fetchone()
        alias = connection.execute("SELECT * FROM github_repo_aliases WHERE alias_repo_id='101'").fetchone()
        snapshot = connection.execute("SELECT * FROM github_repo_snapshots WHERE repo_id='acme/alpha'").fetchone()
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
        identity = connection.execute("SELECT current_database() AS database, current_schema() AS schema").fetchone()
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
        assert repository.record_github_repo_not_found("acme/batch-down", checked_at="2026-07-29") is False
        assert repository.record_github_repo_not_found("acme/batch-down", checked_at="2026-07-29") is True
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
        assert repository.record_github_repo_not_found("acme/batch-keep", checked_at="2026-07-29") is False
        assert repository.record_github_repo_not_found("acme/batch-keep", checked_at="2026-07-29") is True

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
                "SELECT availability_status,stars FROM github_repo_candidates WHERE repo_id='acme/batch-keep'"
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
    assert inputs[0]["heat_snapshot_history"][-1]["snapshot_date"] == "2026-07-28"
    assert inputs[0]["heat_snapshot_history"][-1]["captured_at"] == "2026-07-28T12:00:00+00:00"

    # 基线回溯（断供日无精确昨日快照）：07-26 无快照时取窗口内最近的 07-25
    repository.insert_github_repo_snapshot(
        {
            "repo_id": "acme/alpha",
            "snapshot_date": "2026-07-25",
            "captured_at": "2026-07-25T12:00:00+00:00",
            "stars": 690,
            "forks": 19,
            "watchers": 29,
            "community_metrics_complete": True,
        }
    )
    gap_inputs = repository.get_github_daily_metric_inputs(
        metric_date="2026-07-27",
        previous_date="2026-07-26",
        baseline_start_date="2026-07-20",
        repo_ids=["acme/alpha"],
    )
    assert len(gap_inputs) == 1
    assert gap_inputs[0]["previous_snapshot_date"] == "2026-07-25"
    assert gap_inputs[0]["previous_stars"] == 690
    assert all(s["snapshot_date"] <= "2026-07-27" for s in gap_inputs[0]["heat_snapshot_history"])
    # 窗口下界之外不回溯：baseline_start=07-26 时 07-25 出窗 → 无基线
    out_of_window = repository.get_github_daily_metric_inputs(
        metric_date="2026-07-27",
        previous_date="2026-07-26",
        baseline_start_date="2026-07-26",
        repo_ids=["acme/alpha"],
    )
    assert len(out_of_window) == 1
    assert out_of_window[0]["previous_snapshot_date"] is None

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
    assert status["target_count"] == status["snapshot_count"] == status["metric_count"] == 1
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


def test_v7_rate_scoring_and_version_aware_community_repair(postgres_ingestion) -> None:
    from backend.app.repositories.postgres_github_watcher_repair_repository import PostgresGitHubWatcherRepairRepository
    from backend.app.services.ingestion.github_project_metrics_service import compute_github_daily_metrics

    repository, database = postgres_ingestion
    repo_id = "heat/velocity"
    repository.upsert_github_repo_candidate({"repo_id": repo_id, "full_name": repo_id, "stars": 1740})
    start = datetime(2026, 7, 10, 15, tzinfo=timezone.utc)
    for i in range(5):
        observed = start + timedelta(days=min(i, 3), hours=2 if i == 4 else 0)
        repository.insert_github_repo_snapshot(dict(repo_id=repo_id,
            snapshot_date=(start.date()+timedelta(days=i)).isoformat(),
            captured_at=observed.isoformat(), stars=1000+240*i if i<4 else 1740,
            forks=100+24*i, watchers=10+i, community_metrics_complete=True,
            repo_pushed_at="2026-07-14T00:00:00+00:00"))
    result = compute_github_daily_metrics(metric_date="2026-07-14", repo_ids=[repo_id], db=repository)
    assert result["snapshot_velocity"] == 1 and result["observed_velocity"] == 0
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM github_repo_daily_metrics WHERE repo_id=%s", (repo_id,))
            before = cursor.fetchone()
        assert before["score_version"] == "daily_hot_v7"
        assert before["daily_star_growth"] == 20
        assert before["community_engagement_score"] > 0
        assert PostgresGitHubWatcherRepairRepository().rebuild_daily_community_metrics(
            connection, [repo_id], ["2026-07-14"]
        ) == 1
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM github_repo_daily_metrics WHERE repo_id=%s", (repo_id,))
            after = cursor.fetchone()
        magnitude = 0.625*before["scale_corrected_growth_score"] + 0.375*before["absolute_growth_score"]
        quality = (0.5*before["growth_acceleration_score"] + 0.25*before["maintenance_activity_score"]) / 0.75
        expected = magnitude * (0.8 + 0.2*quality/100)
        assert after["hot_score"] == pytest.approx(expected, abs=0.0001)
        assert after["hot_score"] != before["hot_score"]
        assert after["score_version"] == "daily_hot_v7"
        assert after["community_engagement_score"] == 0


def test_metric_inputs_expose_creation_timestamp_and_prior_cluster(postgres_ingestion) -> None:
    repository, _database = postgres_ingestion
    repo_id = "lure/cluster"
    repository.upsert_github_repo_candidate(
        {"repo_id": repo_id, "full_name": repo_id, "stars": 1600, "created_at": "2026-06-13T12:06:07Z"}
    )
    for day, stars in (("2026-08-20", 1000), ("2026-08-21", 1600)):
        repository.insert_github_repo_snapshot(dict(repo_id=repo_id, snapshot_date=day,
            captured_at=f"{day}T15:00:00+00:00", stars=stars, forks=100, watchers=0,
            community_metrics_complete=True, repo_created_at="2026-06-13"))
    repository.upsert_github_daily_metrics([dict(repo_id=repo_id, metric_date="2026-08-20", stars=1000,
        daily_star_growth=700, daily_growth_available=True, daily_growth_source="snapshot_delta",
        growth_suspicion_score=0.6, growth_suspicion_signals='["coordinated_creation"]')])

    def inputs(metric_date: str, previous_date: str) -> dict[str, Any]:
        rows = repository.get_github_daily_metric_inputs(metric_date=metric_date, previous_date=previous_date,
            baseline_start_date="2026-08-14", repo_ids=[repo_id])
        assert len(rows) == 1
        return rows[0]

    current = inputs("2026-08-21", "2026-08-20")
    # 候选池的 API 时间戳优先于快照里的建仓日期
    assert current["repo_created_at"] == "2026-06-13T12:06:07Z"
    assert current["candidate_created_at"] == "2026-06-13T12:06:07Z"
    assert current["prior_coordinated_creation"] is True
    # 只看目标日之前的窗口：当日自身的标记不回灌
    assert inputs("2026-08-20", "2026-08-19")["prior_coordinated_creation"] is False


def test_snapshot_created_at_backfilled_from_candidate(
    postgres_ingestion: tuple[Any, Any],
) -> None:
    """API created_at 缺失时，快照写入从 candidates 回填权威建仓日期。

    回归：hot_service 曾用 published_date（收录时间）冒充建仓日期，把老仓
    标成 new_repo_surge。固化语义：空入参回填 candidates.created_at、
    显式入参优先、同日冲突保留已有非空值、指标输入读取对遗留空行兜底。
    """
    repository, database = postgres_ingestion
    try:
        repository.upsert_github_repo_candidate(
            {
                "repo_id": "acme/created-fallback",
                "full_name": "acme/created-fallback",
                "created_at": "2024-03-11",
                "stars": 1200,
            }
        )
        # 空入参 → 回填 candidates.created_at
        repository.insert_github_repo_snapshot(
            {
                "repo_id": "acme/created-fallback",
                "snapshot_date": "2026-08-19",
                "captured_at": "2026-08-19T01:00:00+00:00",
                "stars": 1200,
                "forks": 30,
                "watchers": 30,
                "community_metrics_complete": True,
                "repo_created_at": "",
            }
        )
        # 显式入参优先于回填
        repository.insert_github_repo_snapshot(
            {
                "repo_id": "acme/created-fallback",
                "snapshot_date": "2026-08-18",
                "captured_at": "2026-08-18T01:00:00+00:00",
                "stars": 1190,
                "forks": 29,
                "watchers": 29,
                "community_metrics_complete": True,
                "repo_created_at": "2024-03-10",
            }
        )
        # 同日冲突：已有非空值不被空入参覆盖
        repository.insert_github_repo_snapshot(
            {
                "repo_id": "acme/created-fallback",
                "snapshot_date": "2026-08-18",
                "captured_at": "2026-08-18T02:00:00+00:00",
                "stars": 1195,
                "forks": 29,
                "watchers": 29,
                "community_metrics_complete": True,
                "repo_created_at": "",
            }
        )
        # 遗留空行：绕过写入 SQL 直接插入空 created_at，验证读侧兜底
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO github_repo_snapshots (repo_id, snapshot_date, "
                "captured_at, stars, forks, watchers, community_metrics_complete, "
                "open_issues, repo_created_at, repo_pushed_at) VALUES "
                "('acme/created-fallback', '2026-08-17', "
                "'2026-08-17T01:00:00+00:00', 1180, 28, 28, TRUE, 0, '', '')"
            )
            rows = connection.execute(
                "SELECT snapshot_date, repo_created_at FROM github_repo_snapshots "
                "WHERE repo_id='acme/created-fallback' ORDER BY snapshot_date"
            ).fetchall()
        by_date = {row["snapshot_date"]: row["repo_created_at"] for row in rows}
        assert by_date["2026-08-17"] == ""
        assert by_date["2026-08-18"] == "2024-03-10"
        assert by_date["2026-08-19"] == "2024-03-11"

        inputs = repository.get_github_daily_metric_inputs(
            metric_date="2026-08-17",
            previous_date="2026-08-16",
            baseline_start_date="2026-08-10",
            repo_ids=["acme/created-fallback"],
        )
        assert len(inputs) == 1
        assert inputs[0]["repo_created_at"] == "2024-03-11"
    finally:
        _delete_candidates(database, "acme/created-fallback")


def test_candidate_created_at_follows_github_api(
    postgres_ingestion: tuple[Any, Any],
) -> None:
    """建仓时间以 GitHub API 为准：日期不同即纠正，同日只接受更精确的时间戳，
    空值不清除已有值。"""
    repository, database = postgres_ingestion
    repo_id = "acme/created-heal"

    def created_at() -> str:
        with database.transaction() as connection:
            row = connection.execute(
                "SELECT created_at FROM github_repo_candidates WHERE repo_id=%s", (repo_id,)
            ).fetchone()
        return row["created_at"]

    def upsert(value: str) -> None:
        repository.upsert_github_repo_candidate(
            {"repo_id": repo_id, "full_name": repo_id, "stars": 900, "created_at": value}
        )

    try:
        upsert("2026-09-28")  # 历史遗留：收录日冒充的建仓日期
        upsert("2024-03-11")
        assert created_at() == "2024-03-11"
        upsert("2024-03-11T08:09:10Z")
        assert created_at() == "2024-03-11T08:09:10Z"
        upsert("2024-03-11")
        assert created_at() == "2024-03-11T08:09:10Z"
        upsert("")
        assert created_at() == "2024-03-11T08:09:10Z"
    finally:
        _delete_candidates(database, repo_id)


def test_metric_inputs_prefer_candidate_creation_over_polluted_snapshot(
    postgres_ingestion: tuple[Any, Any],
) -> None:
    """快照里遗留的错误建仓日期（Trending 抓取日）不得盖过候选池的 API 值。"""
    repository, database = postgres_ingestion
    repo_id = "acme/created-polluted"
    try:
        repository.upsert_github_repo_candidate(
            {"repo_id": repo_id, "full_name": repo_id, "stars": 5000, "created_at": "2023-01-05"}
        )
        with database.transaction() as connection:
            connection.execute(
                "INSERT INTO github_repo_snapshots (repo_id, snapshot_date, "
                "captured_at, stars, forks, watchers, community_metrics_complete, "
                "open_issues, repo_created_at, repo_pushed_at) VALUES "
                "(%s, '2026-09-28', '2026-09-28T01:00:00+00:00', 5000, 40, 40, TRUE, 0, "
                "'2026-09-28', '')",
                (repo_id,),
            )
        rows = repository.get_github_daily_metric_inputs(
            metric_date="2026-09-28",
            previous_date="2026-09-27",
            baseline_start_date="2026-09-21",
            repo_ids=[repo_id],
        )
        assert len(rows) == 1
        assert rows[0]["repo_created_at"] == "2023-01-05"
    finally:
        _delete_candidates(database, repo_id)
