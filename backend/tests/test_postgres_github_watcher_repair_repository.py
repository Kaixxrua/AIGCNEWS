from __future__ import annotations

from unittest.mock import MagicMock

from backend.app.repositories.postgres_github_watcher_repair_repository import (
    PostgresGitHubWatcherRepairRepository,
)


def _cursor(connection: MagicMock) -> MagicMock:
    return connection.cursor.return_value.__enter__.return_value


def test_fetch_target_identity_reads_current_database_and_schema() -> None:
    connection = MagicMock()
    cursor = _cursor(connection)
    cursor.fetchone.return_value = {"database": "catalog", "schema": "public"}
    repository = PostgresGitHubWatcherRepairRepository()

    identity = repository.fetch_target_identity(connection)

    assert identity == {"database": "catalog", "schema": "public"}
    assert "current_database()" in cursor.execute.call_args.args[0]
    assert "current_schema()" in cursor.execute.call_args.args[0]


def test_fetch_schema_version_defaults_to_zero_when_empty() -> None:
    connection = MagicMock()
    cursor = _cursor(connection)
    cursor.fetchone.return_value = None
    repository = PostgresGitHubWatcherRepairRepository()

    assert repository.fetch_schema_version(connection) is None
    sql = cursor.execute.call_args.args[0]
    assert "COALESCE(MAX(version), 0)" in sql
    assert "app_schema_migrations" in sql

    cursor.fetchone.return_value = {"version": 12}
    assert repository.fetch_schema_version(connection) == 12


def test_try_acquire_repair_lock_reports_boolean_flag() -> None:
    connection = MagicMock()
    cursor = _cursor(connection)
    repository = PostgresGitHubWatcherRepairRepository()

    cursor.fetchone.return_value = {"acquired": True}
    assert repository.try_acquire_repair_lock(connection, 42) is True
    assert cursor.execute.call_args.args == (
        "SELECT pg_try_advisory_xact_lock(%s) AS acquired",
        (42,),
    )

    cursor.fetchone.return_value = {"acquired": False}
    assert repository.try_acquire_repair_lock(connection, 42) is False


def test_find_corrupted_snapshots_scans_legacy_window_without_cursor() -> None:
    connection = MagicMock()
    cursor = _cursor(connection)
    cursor.fetchall.return_value = [{"id": 1}]
    repository = PostgresGitHubWatcherRepairRepository()

    rows = repository.find_corrupted_snapshots(
        connection,
        corruption_end_date="2026-07-30",
        batch_size=500,
        cursor=None,
        for_update=False,
    )

    assert rows == [{"id": 1}]
    sql, params = cursor.execute.call_args.args
    assert "FROM github_repo_snapshots" in sql
    assert "community_metrics_complete IS TRUE" in sql
    assert "watchers=stars AND stars>=500" in sql
    assert "snapshot_date<=%s" in sql
    assert "(snapshot_date, repo_id) >" not in sql
    assert "FOR UPDATE" not in sql
    assert params == ("2026-07-30", 500)


def test_find_corrupted_snapshots_pages_with_cursor_and_locks_for_update() -> None:
    connection = MagicMock()
    cursor = _cursor(connection)
    cursor.fetchall.return_value = []
    repository = PostgresGitHubWatcherRepairRepository()

    repository.find_corrupted_snapshots(
        connection,
        corruption_end_date="2026-07-30",
        batch_size=25,
        cursor=("2026-07-01", "acme/repo"),
        for_update=True,
    )

    sql, params = cursor.execute.call_args.args
    assert "AND (snapshot_date, repo_id) > (%s, %s)" in sql
    assert sql.endswith(" FOR UPDATE")
    assert "ORDER BY snapshot_date,repo_id LIMIT %s" in sql
    assert params == ("2026-07-30", "2026-07-01", "acme/repo", 25)


def test_has_corrupted_snapshots_after_checks_existence() -> None:
    connection = MagicMock()
    cursor = _cursor(connection)
    repository = PostgresGitHubWatcherRepairRepository()

    cursor.fetchone.return_value = {"has_more": True}
    assert (
        repository.has_corrupted_snapshots_after(
            connection,
            corruption_end_date="2026-07-30",
            cursor=None,
        )
        is True
    )
    sql, params = cursor.execute.call_args.args
    assert "SELECT EXISTS(SELECT 1 FROM github_repo_snapshots" in sql
    assert params == ("2026-07-30",)

    cursor.fetchone.return_value = {"has_more": False}
    assert (
        repository.has_corrupted_snapshots_after(
            connection,
            corruption_end_date="2026-07-30",
            cursor=("2026-07-01", "acme/repo"),
        )
        is False
    )
    sql, params = cursor.execute.call_args.args
    assert "AND (snapshot_date, repo_id) > (%s, %s)" in sql
    assert params == ("2026-07-30", "2026-07-01", "acme/repo")


def test_quarantine_corrupted_snapshots_marks_rows_incomplete() -> None:
    connection = MagicMock()
    cursor = _cursor(connection)
    cursor.rowcount = 2
    repository = PostgresGitHubWatcherRepairRepository()

    assert repository.quarantine_corrupted_snapshots(connection, [7, 9]) == 2
    sql, params = cursor.execute.call_args.args
    assert "UPDATE github_repo_snapshots" in sql
    assert "watchers=0,community_metrics_complete=FALSE" in sql
    assert "id=ANY(%s)" in sql
    assert "watchers=stars AND stars>=500" in sql
    assert params == ([7, 9],)


def test_reset_candidate_watchers_uses_latest_complete_snapshot() -> None:
    connection = MagicMock()
    cursor = _cursor(connection)
    cursor.rowcount = 1
    repository = PostgresGitHubWatcherRepairRepository()

    assert repository.reset_candidate_watchers(connection, ["acme/repo"]) == 1
    sql, params = cursor.execute.call_args.args
    assert "WITH latest_complete AS" in sql
    assert "UPDATE github_repo_candidates AS candidate" in sql
    assert "COALESCE(latest_complete.watchers,0)" in sql
    assert params == (["acme/repo"], ["acme/repo"])


def test_clear_daily_watcher_metrics_zeroes_selected_dates() -> None:
    connection = MagicMock()
    cursor = _cursor(connection)
    cursor.rowcount = 1
    repository = PostgresGitHubWatcherRepairRepository()

    cleared = repository.clear_daily_watcher_metrics(
        connection, ["acme/repo"], ["2026-07-28"]
    )

    assert cleared == 1
    sql, params = cursor.execute.call_args.args
    assert "UPDATE github_repo_daily_metrics AS metrics SET watchers=0" in sql
    assert "UNNEST(%s::text[],%s::text[])" in sql
    assert params == (["acme/repo"], ["2026-07-28"])


def test_rebuild_daily_community_metrics_recomputes_hot_score_without_version_change() -> None:
    connection = MagicMock()
    cursor = _cursor(connection)
    cursor.rowcount = 2
    repository = PostgresGitHubWatcherRepairRepository()

    rebuilt = repository.rebuild_daily_community_metrics(
        connection, ["acme/repo"], ["2026-07-28", "2026-07-29"]
    )

    assert rebuilt == 2
    sql, params = cursor.execute.call_args.args
    assert "daily_fork_growth=0" in sql
    assert "daily_watcher_growth=0" in sql
    assert "community_engagement_score=0.0" in sql
    assert "0.55*scale_corrected_growth_score" in sql
    assert "0.20*growth_acceleration_score" in sql
    assert "0.10*absolute_growth_score" in sql
    assert "0.10*maintenance_activity_score" in sql
    assert "updated_at=CURRENT_TIMESTAMP::text" in sql
    assert "score_version='daily_hot_v6'" in sql
    assert params == (["acme/repo"], ["2026-07-28", "2026-07-29"])
