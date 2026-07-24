from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from backend.app.services.project_catalog_transfer import (
    CANDIDATE_SPEC,
    TABLE_TRANSFER_SPEC_BY_NAME,
    TABLE_TRANSFER_SPECS,
    CandidateCheckpoint,
    TableCheckpoint,
    ProjectCatalogTransferCollisionError,
    ProjectCatalogTransferSafetyError,
    ProjectCatalogTransferService,
    TargetIdentity,
    _advisory_lock_id,
    candidate_batch_digest,
    is_retryable_database_error,
    source_identity_sha256,
)


class ErrorWithSqlstate(RuntimeError):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("database failure")
        self.sqlstate = sqlstate


def settings(*, env: str = "development") -> SimpleNamespace:
    return SimpleNamespace(
        env=env,
        mysql_host="mysql.internal",
        mysql_port=3306,
        mysql_database="catalog_source",
    )


def candidate(repo_id: str = "owner/repo", full_name: str = "Owner/Repo") -> dict[str, Any]:
    return {
        "repo_id": repo_id,
        "full_name": full_name,
        "title": "Repo",
        "url": "https://github.com/Owner/Repo",
        "description": "Description",
        "language": "Python",
        "topics_json": '["ai"]',
        "created_at": "2026-01-01T00:00:00Z",
        "pushed_at": "2026-01-02T00:00:00Z",
        "stars": 10,
        "forks": 2,
        "watchers": 3,
        "source_channels": "trending_daily",
        "first_seen_at": "2026-01-03T00:00:00Z",
        "last_seen_at": "2026-01-04T00:00:00Z",
        "last_snapshot_at": "2026-01-04T00:00:00Z",
        "availability_status": "active",
        "not_found_count": 0,
        "availability_checked_at": None,
    }


def test_full_transfer_specs_are_dependency_ordered_and_explicit() -> None:
    assert [spec.name for spec in TABLE_TRANSFER_SPECS] == [
        "github_repo_candidates",
        "github_repo_aliases",
        "github_repo_enrichments",
        "github_repo_snapshots",
        "github_repo_daily_metrics",
        "github_trending_hits",
        "github_repo_recommendations",
        "github_project_semantic_sources",
        "tool_websites",
        "tool_website_enrichments",
        "project_favorites",
        "user_tool_websites",
        "user_tool_website_overrides",
    ]
    seen: set[str] = set()
    for spec in TABLE_TRANSFER_SPECS:
        assert spec.columns
        assert spec.cursor_columns
        assert spec.conflict_columns
        assert set(spec.cursor_columns) <= set(spec.columns)
        assert set(spec.conflict_columns) <= set(spec.columns)
        assert set(spec.boolean_columns) <= set(spec.columns)
        assert set(spec.datetime_columns) <= set(spec.columns)
        assert set(spec.non_null_default_columns) <= set(spec.columns)
        assert set(spec.dependencies) <= seen
        seen.add(spec.name)


def test_transfer_specs_capture_composite_cursor_codecs_and_identities() -> None:
    by_name = {spec.name: spec for spec in TABLE_TRANSFER_SPECS}
    assert CANDIDATE_SPEC.columns == tuple(candidate().keys())
    assert by_name["github_repo_daily_metrics"].cursor_columns == (
        "repo_id",
        "metric_date",
    )
    assert by_name["github_repo_snapshots"].boolean_columns == (
        "community_metrics_complete",
    )
    assert by_name["github_repo_recommendations"].datetime_columns == (
        "recommended_at",
        "updated_at",
    )
    assert {
        spec.name for spec in TABLE_TRANSFER_SPECS if spec.identity_column == "id"
    } == {
        "github_repo_snapshots",
        "github_trending_hits",
        "tool_websites",
        "project_favorites",
        "user_tool_websites",
        "user_tool_website_overrides",
    }


def test_source_row_codecs_reject_lossy_nulls_and_normalize_types() -> None:
    service = ProjectCatalogTransferService(mysql=object(), postgres=object(), config=settings())  # type: ignore[arg-type]
    recommendation = TABLE_TRANSFER_SPEC_BY_NAME["github_repo_recommendations"]
    row = service._encode_source_row(
        recommendation,
        {
            "repo_id": "owner/repo",
            "active": 1,
            "recommended_by_user_id": None,
            "recommended_at": datetime(2026, 1, 1, 8),
            "updated_at": datetime(2026, 1, 1, 8),
        },
        source_timezone="Asia/Shanghai",
    )
    assert row["active"] is True
    assert row["recommended_at"] == datetime(2026, 1, 1, tzinfo=timezone.utc)

    candidate_row = candidate()
    candidate_row["stars"] = None
    with pytest.raises(ProjectCatalogTransferSafetyError, match="not nullable"):
        service._encode_source_row(
            CANDIDATE_SPEC,
            candidate_row,
            source_timezone="UTC",
        )


def test_mysql_source_query_quotes_reserved_columns() -> None:
    cursor = BatchCursor()
    connection = BatchConnection(cursor)

    class SourceDatabase:
        @contextmanager
        def transaction(self):
            yield connection

    service = ProjectCatalogTransferService(
        mysql=SourceDatabase(),  # type: ignore[arg-type]
        postgres=object(),  # type: ignore[arg-type]
        config=settings(),
    )
    service._read_table_batch(
        TABLE_TRANSFER_SPEC_BY_NAME["github_trending_hits"],
        after={},
        batch_size=10,
        source_timezone="UTC",
    )
    assert "`rank`" in cursor.calls[-1][0]


def test_composite_cursor_batch_uses_tuple_keyset_pagination() -> None:
    class SourceCursor(BatchCursor):
        def fetchall(self) -> list[dict[str, Any]]:
            return []

    cursor = SourceCursor()
    connection = BatchConnection(cursor)

    class SourceDatabase:
        @contextmanager
        def transaction(self):
            yield connection

    service = ProjectCatalogTransferService(
        mysql=SourceDatabase(),  # type: ignore[arg-type]
        postgres=object(),  # type: ignore[arg-type]
        config=settings(),
    )
    spec = TABLE_TRANSFER_SPEC_BY_NAME["github_repo_daily_metrics"]
    service._read_table_batch(
        spec,
        after={"repo_id": "a/repo", "metric_date": "2026-01-01"},
        batch_size=10,
        source_timezone="UTC",
    )
    sql, params = cursor.calls[-1]
    assert "WHERE (BINARY `repo_id`, BINARY `metric_date`) > (BINARY %s, BINARY %s)" in sql
    assert "ORDER BY BINARY `repo_id`, BINARY `metric_date` ASC" in sql
    assert params == ("a/repo", "2026-01-01", 10)


def test_generic_batch_upsert_and_checkpoint_are_atomic() -> None:
    cursor = BatchCursor()
    connection = BatchConnection(cursor)
    service = ProjectCatalogTransferService(mysql=object(), postgres=object(), config=settings())  # type: ignore[arg-type]
    spec = TABLE_TRANSFER_SPEC_BY_NAME["github_repo_aliases"]
    row = {
        "alias_repo_id": "old/repo",
        "canonical_repo_id": "owner/repo",
        "full_name": "Old/Repo",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
    }
    result = service._write_table_batch(
        connection,
        spec=spec,
        job_id="job",
        checkpoint=TableCheckpoint({}, 0, 0, "pending"),
        rows=[row],
    )
    assert connection.events == ["begin", "commit"]
    assert "ON CONFLICT (alias_repo_id) DO UPDATE" in cursor.executemany_calls[0][0]
    assert "UPDATE project_catalog_migration_checkpoints" in cursor.calls[-1][0]
    assert result.cursor == {"alias_repo_id": "old/repo"}


def test_identity_sequence_repair_handles_nonempty_and_empty_tables() -> None:
    cursor = BatchCursor()
    for spec in TABLE_TRANSFER_SPECS:
        if spec.identity_column is None:
            continue
        cursor.fetchone_values.extend(
            [
                {"sequence_name": f"public.{spec.name}_{spec.identity_column}_seq"},
                {"maximum_id": None if spec.name == "project_favorites" else 42},
            ]
        )
    connection = BatchConnection(cursor)
    repairs = ProjectCatalogTransferService._repair_identity_sequences(connection)
    assert connection.events == ["begin", "commit"]
    assert len(repairs) == 6
    setval_calls = [(sql, params) for sql, params in cursor.calls if "setval" in sql]
    assert any(sql.endswith("1, false)") for sql, _ in setval_calls)
    assert any(sql.endswith("%s, true)") for sql, _ in setval_calls)
    assert not any("nextval" in sql.lower() for sql, _ in cursor.calls)


def test_transfer_lock_serializes_all_jobs_for_one_target_table() -> None:
    first = _advisory_lock_id("catalog", "public", "github_repo_candidates")
    second = _advisory_lock_id("catalog", "public", "github_repo_candidates")
    other_schema = _advisory_lock_id("catalog", "staging", "github_repo_candidates")
    assert first == second
    assert first != other_schema


def test_source_identity_is_stable_and_does_not_depend_on_password() -> None:
    first = settings()
    first.mysql_password = "secret-one"
    second = settings()
    second.mysql_password = "secret-two"

    assert source_identity_sha256(first) == source_identity_sha256(second)
    assert len(source_identity_sha256(first)) == 64


def test_candidate_digest_is_deterministic_and_sensitive_to_rows() -> None:
    row = candidate()
    assert candidate_batch_digest([row]) == candidate_batch_digest([dict(row)])
    changed = dict(row, stars=11)
    assert candidate_batch_digest([row]) != candidate_batch_digest([changed])


@pytest.mark.parametrize("sqlstate", ["08006", "40001", "40P01", "55P03"])
def test_retryable_sqlstates_are_classified(sqlstate: str) -> None:
    assert is_retryable_database_error(ErrorWithSqlstate(sqlstate)) is True


def test_constraint_errors_are_not_retried() -> None:
    assert is_retryable_database_error(ErrorWithSqlstate("23505")) is False


def test_plan_is_read_only_and_reports_counts() -> None:
    service = ProjectCatalogTransferService(mysql=object(), postgres=object(), config=settings())  # type: ignore[arg-type]
    with (
        patch.object(
            service,
            "_inspect_target",
            return_value=TargetIdentity("catalog_test", "public", 2),
        ),
        patch.object(service, "_source_candidate_count", return_value=11),
        patch.object(service, "_target_candidate_count", return_value=3),
        patch.object(service, "_ensure_run_and_checkpoint") as ensure_run,
    ):
        result = service.plan(
            job_id="candidate-plan",
            batch_size=5,
            target_database="catalog_test",
            target_schema="public",
        )

    assert result["status"] == "dry_run"
    assert result["estimated_batches"] == 3
    assert result["source_count"] == 11
    assert result["target_count"] == 3
    ensure_run.assert_not_called()


def test_load_without_apply_remains_a_plan() -> None:
    service = ProjectCatalogTransferService(mysql=object(), postgres=object(), config=settings())  # type: ignore[arg-type]
    with patch.object(service, "plan", return_value={"status": "dry_run"}) as plan:
        result = service.load_candidates(
            job_id="job",
            target_database="catalog_test",
            target_schema="public",
        )
    assert result == {"status": "dry_run"}
    plan.assert_called_once()


def test_production_requires_two_independent_authorizations(monkeypatch: pytest.MonkeyPatch) -> None:
    service = ProjectCatalogTransferService(mysql=object(), postgres=object(), config=settings(env="production"))  # type: ignore[arg-type]
    monkeypatch.delenv("PROJECT_CATALOG_MIGRATION_PRODUCTION_AUTHORIZED", raising=False)
    with pytest.raises(ProjectCatalogTransferSafetyError, match="independent"):
        service._validate_production_authorization(True)

    monkeypatch.setenv("PROJECT_CATALOG_MIGRATION_PRODUCTION_AUTHORIZED", "true")
    with pytest.raises(ProjectCatalogTransferSafetyError, match="independent"):
        service._validate_production_authorization(False)
    service._validate_production_authorization(True)


class BatchCursor:
    def __init__(self, existing: list[dict[str, Any]] | None = None) -> None:
        self.existing = existing or []
        self.calls: list[tuple[str, Any]] = []
        self.executemany_calls: list[tuple[str, Any]] = []
        self.fetchone_values: list[Any] = []

    def __enter__(self) -> "BatchCursor":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.calls.append((sql, params))

    def executemany(self, sql: str, params: Any) -> None:
        self.executemany_calls.append((sql, params))

    def fetchall(self) -> list[dict[str, Any]]:
        return self.existing

    def fetchone(self) -> Any:
        return self.fetchone_values.pop(0)


class BatchConnection:
    def __init__(self, cursor: BatchCursor, *, fail_commit: bool = False) -> None:
        self.cursor_value = cursor
        self.fail_commit = fail_commit
        self.events: list[str] = []

    def cursor(self) -> BatchCursor:
        return self.cursor_value

    @contextmanager
    def transaction(self):
        self.events.append("begin")
        try:
            yield
            if self.fail_commit:
                raise ErrorWithSqlstate("40001")
        except BaseException:
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")


def test_batch_upsert_and_checkpoint_share_one_transaction() -> None:
    cursor = BatchCursor()
    connection = BatchConnection(cursor)
    service = ProjectCatalogTransferService(mysql=object(), postgres=object(), config=settings())  # type: ignore[arg-type]
    checkpoint = CandidateCheckpoint("", 0, 0, "running")

    result = service._write_candidate_batch(
        connection,
        job_id="job",
        checkpoint=checkpoint,
        rows=[candidate()],
    )

    assert connection.events == ["begin", "commit"]
    assert len(cursor.executemany_calls) == 1
    assert "ON CONFLICT (repo_id) DO UPDATE" in cursor.executemany_calls[0][0]
    assert "UPDATE project_catalog_migration_checkpoints" in cursor.calls[-1][0]
    assert result.cursor == "owner/repo"
    assert result.rows_processed == 1


def test_batch_failure_rolls_back_checkpoint_with_target_rows() -> None:
    cursor = BatchCursor()
    connection = BatchConnection(cursor, fail_commit=True)
    service = ProjectCatalogTransferService(mysql=object(), postgres=object(), config=settings())  # type: ignore[arg-type]

    with pytest.raises(ErrorWithSqlstate):
        service._write_candidate_batch(
            connection,
            job_id="job",
            checkpoint=CandidateCheckpoint("", 0, 0, "running"),
            rows=[candidate()],
        )

    assert connection.events == ["begin", "rollback"]
    assert "UPDATE project_catalog_migration_checkpoints" in cursor.calls[-1][0]


def test_case_insensitive_full_name_collision_fails_before_upsert() -> None:
    cursor = BatchCursor(existing=[{"repo_id": "other/repo", "full_name": "owner/repo"}])
    connection = BatchConnection(cursor)
    service = ProjectCatalogTransferService(mysql=object(), postgres=object(), config=settings())  # type: ignore[arg-type]

    with pytest.raises(ProjectCatalogTransferCollisionError, match="collision"):
        service._write_candidate_batch(
            connection,
            job_id="job",
            checkpoint=CandidateCheckpoint("", 0, 0, "running"),
            rows=[candidate()],
        )

    assert cursor.executemany_calls == []
    assert connection.events == ["begin", "rollback"]


def test_completed_job_ids_are_immutable() -> None:
    service = ProjectCatalogTransferService(mysql=object(), postgres=object(), config=settings())  # type: ignore[arg-type]
    cursor = MagicMock()
    cursor.fetchone.return_value = {
        "source_identity_sha256": source_identity_sha256(settings()),
        "target_database": "catalog_test",
        "target_schema": "public",
        "schema_version": 2,
        "options_json": {"batch_size": 10, "codec_version": 1, "tables": ["github_repo_candidates"]},
        "status": "completed",
    }
    @contextmanager
    def transaction():
        yield

    connection = MagicMock()
    connection.transaction.side_effect = transaction
    connection.cursor.return_value.__enter__.return_value = cursor
    with pytest.raises(ProjectCatalogTransferSafetyError, match="immutable"):
        service._ensure_run_and_checkpoint(
            connection,
            job_id="completed-job",
            target=TargetIdentity("catalog_test", "public", 2),
            options={"batch_size": 10, "codec_version": 1, "tables": ["github_repo_candidates"]},
        )


def test_retry_reuses_operation_and_is_bounded() -> None:
    delays: list[float] = []
    service = ProjectCatalogTransferService(
        mysql=object(),  # type: ignore[arg-type]
        postgres=object(),  # type: ignore[arg-type]
        config=settings(),
        sleep=delays.append,
        random_value=lambda: 0.5,
    )
    outcomes: list[Any] = [ErrorWithSqlstate("40001"), {"status": "completed"}]

    def load_once(**_: Any) -> dict[str, Any]:
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    with patch.object(service, "_load_candidates_once", side_effect=load_once) as load:
        result = service.load_candidates(
            job_id="job",
            batch_size=10,
            target_database="catalog_test",
            target_schema="public",
            apply=True,
        )

    assert result["status"] == "completed"
    assert load.call_count == 2
    assert delays == [0.125]


def test_terminal_failure_is_recorded_without_sensitive_message() -> None:
    service = ProjectCatalogTransferService(
        mysql=object(),  # type: ignore[arg-type]
        postgres=object(),  # type: ignore[arg-type]
        config=settings(),
    )
    error = ErrorWithSqlstate("23505")
    with (
        patch.object(service, "_load_candidates_once", side_effect=error),
        patch.object(service, "_record_failure_best_effort") as record,
        pytest.raises(ErrorWithSqlstate),
    ):
        service.load_candidates(
            job_id="job",
            target_database="catalog_test",
            target_schema="public",
            apply=True,
        )
    record.assert_called_once_with(
        job_id="job", attempt=1, error=error, retryable=False
    )
