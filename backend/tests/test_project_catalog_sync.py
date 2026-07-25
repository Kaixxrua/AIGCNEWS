from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest

from backend.app.services.project_catalog_sync import (
    OutboxEvent,
    ProjectCatalogReconciliationWriter,
    ProjectCatalogSyncPermanentError,
    ProjectCatalogSyncWorker,
)
from backend.app.services.project_catalog_transfer import TABLE_TRANSFER_SPEC_BY_NAME


class TransactionalDatabase:
    def __init__(self, connection: MagicMock) -> None:
        self.connection = connection
        self.transactions = 0

    @contextmanager
    def transaction(self) -> Iterator[MagicMock]:
        self.transactions += 1
        yield self.connection


def _event(**overrides: Any) -> OutboxEvent:
    values = {
        "id": 7,
        "event_id": "00000000-0000-0000-0000-000000000007",
        "aggregate_type": "github_repo_candidates",
        "aggregate_key": {"repo_id": "repo-7"},
        "operation": "reconcile",
        "source_method": "test",
        "attempt_count": 1,
        "lease_token": "00000000-0000-0000-0000-000000000008",
    }
    values.update(overrides)
    return OutboxEvent(**values)


def test_key_columns_accept_only_declared_exact_identity_shapes() -> None:
    snapshot = TABLE_TRANSFER_SPEC_BY_NAME["github_repo_snapshots"]
    favorite = TABLE_TRANSFER_SPEC_BY_NAME["project_favorites"]

    assert ProjectCatalogReconciliationWriter._key_columns(
        snapshot, {"repo_id": "r", "snapshot_date": "2026-07-23"}
    ) == ("repo_id", "snapshot_date")
    assert ProjectCatalogReconciliationWriter._key_columns(
        favorite,
        {"user_id": 1, "project_source": "website", "project_id": "2"},
    ) == ("user_id", "project_source", "project_id")
    with pytest.raises(ProjectCatalogSyncPermanentError):
        ProjectCatalogReconciliationWriter._key_columns(snapshot, {"repo_id": "r"})


def test_natural_key_upsert_uses_event_identity_conflict_target() -> None:
    cursor = MagicMock()
    spec = TABLE_TRANSFER_SPEC_BY_NAME["project_favorites"]
    row = {column: None for column in spec.columns}
    row.update(
        id=12,
        user_id=3,
        project_source="website",
        project_id="42",
    )

    ProjectCatalogReconciliationWriter._upsert_target_row(
        cursor,
        spec,
        row,
        ("user_id", "project_source", "project_id"),
    )

    sql = cursor.execute.call_args.args[0]
    assert "ON CONFLICT (user_id, project_source, project_id)" in sql
    assert "id = EXCLUDED.id" in sql


def test_duplicate_applied_event_skips_mutation_after_marker_conflict() -> None:
    mysql_connection = MagicMock()
    postgres_connection = MagicMock()
    postgres_cursor = postgres_connection.cursor.return_value.__enter__.return_value
    postgres_cursor.fetchone.return_value = None
    writer = ProjectCatalogReconciliationWriter(
        TransactionalDatabase(mysql_connection),  # type: ignore[arg-type]
        TransactionalDatabase(postgres_connection),  # type: ignore[arg-type]
    )
    writer._read_source_row = MagicMock(return_value={"repo_id": "repo-7"})

    writer.apply(_event())

    assert postgres_cursor.execute.call_count == 2
    lock_sql = postgres_cursor.execute.call_args_list[0].args[0]
    marker_sql = postgres_cursor.execute.call_args_list[1].args[0]
    assert "pg_advisory_xact_lock" in lock_sql
    assert "INSERT INTO project_catalog_applied_events" in marker_sql
    assert "ON CONFLICT DO NOTHING" in marker_sql
    assert "RETURNING event_id" in marker_sql
    writer._read_source_row.assert_not_called()


def test_aggregate_lock_is_stable_and_key_order_independent() -> None:
    first_key = json.dumps(
        {"repo_id": "r", "snapshot_date": "2026-07-23"},
        sort_keys=True,
        separators=(",", ":"),
    )
    reordered_key = json.dumps(
        {"snapshot_date": "2026-07-23", "repo_id": "r"},
        sort_keys=True,
        separators=(",", ":"),
    )

    first = ProjectCatalogReconciliationWriter._aggregate_lock_id(
        "github_repo_snapshots", first_key
    )
    second = ProjectCatalogReconciliationWriter._aggregate_lock_id(
        "github_repo_snapshots", reordered_key
    )
    other = ProjectCatalogReconciliationWriter._aggregate_lock_id(
        "github_repo_daily_metrics", reordered_key
    )

    assert first == second
    assert first != other


def test_writer_locks_and_marks_before_reading_current_source_state() -> None:
    calls: list[str] = []
    postgres_connection = MagicMock()
    postgres_cursor = postgres_connection.cursor.return_value.__enter__.return_value

    def execute(sql: str, *_args: Any) -> None:
        calls.append("lock" if "pg_advisory_xact_lock" in sql else "marker")

    postgres_cursor.execute.side_effect = execute
    postgres_cursor.fetchone.return_value = {"event_id": "event-7"}
    writer = ProjectCatalogReconciliationWriter(
        TransactionalDatabase(MagicMock()),  # type: ignore[arg-type]
        TransactionalDatabase(postgres_connection),  # type: ignore[arg-type]
    )
    writer._read_source_row = MagicMock(
        side_effect=lambda *_args: calls.append("read") or None
    )
    writer._delete_target_row = MagicMock(
        side_effect=lambda *_args: calls.append("mutation")
    )

    writer.apply(_event())

    assert calls == ["lock", "marker", "read", "mutation"]


def test_malformed_claimed_row_is_dead_lettered() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [{"id": 9}],
        [{
            "id": 9,
            "event_id": "event-9",
            "aggregate_type": "tool_websites",
            "aggregate_key": "[1]",
            "operation": "reconcile",
            "source_method": "test",
            "attempt_count": 1,
            "lease_token": "lease-9",
        }],
    ]
    cursor.rowcount = 1
    worker = ProjectCatalogSyncWorker(
        TransactionalDatabase(connection),  # type: ignore[arg-type]
        writer=MagicMock(),
    )

    assert worker.claim() == []
    assert any(
        "SET status = 'dead'" in call.args[0]
        for call in cursor.execute.call_args_list
    )


def test_claim_uses_short_fenced_mysql_transaction() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [{"id": 7}],
        [
            {
                "id": 7,
                "event_id": "00000000-0000-0000-0000-000000000007",
                "aggregate_type": "github_repo_candidates",
                "aggregate_key": '{"repo_id":"repo-7"}',
                "operation": "reconcile",
                "source_method": "test",
                "attempt_count": 2,
                "lease_token": "lease-7",
            }
        ],
    ]
    worker = ProjectCatalogSyncWorker(
        TransactionalDatabase(connection),  # type: ignore[arg-type]
        writer=MagicMock(),
        batch_size=5,
        lease_seconds=30,
    )

    events = worker.claim()

    assert events[0].aggregate_key == {"repo_id": "repo-7"}
    sql = [call.args[0] for call in cursor.execute.call_args_list]
    assert "FOR UPDATE SKIP LOCKED" in sql[0]
    assert "attempt_count = attempt_count + 1" in sql[1]
    assert "lease_token" in sql[2]


def test_run_once_acks_after_writer_returns() -> None:
    writer = MagicMock()
    worker = ProjectCatalogSyncWorker(MagicMock(), writer=writer)
    event = _event()
    worker.claim = MagicMock(return_value=[event])
    worker._ack = MagicMock()
    worker._fail = MagicMock()

    result = worker.run_once()

    writer.apply.assert_called_once_with(event)
    worker._ack.assert_called_once_with(event)
    worker._fail.assert_not_called()
    assert result.processed == 1


def test_event_parser_rejects_invalid_event_id_and_operation() -> None:
    base = {
        "id": 1,
        "event_id": "not-a-uuid",
        "aggregate_type": "tool_websites",
        "aggregate_key": json.dumps({"id": 1}),
        "operation": "reconcile",
        "source_method": "test",
        "attempt_count": 1,
        "lease_token": "lease",
    }
    with pytest.raises(ProjectCatalogSyncPermanentError):
        ProjectCatalogSyncWorker._event(base)
    base["event_id"] = "00000000-0000-0000-0000-000000000001"
    base["operation"] = "unknown"
    with pytest.raises(ProjectCatalogSyncPermanentError):
        ProjectCatalogSyncWorker._event(base)


def test_event_parser_rejects_non_object_key() -> None:
    with pytest.raises(ProjectCatalogSyncPermanentError):
        ProjectCatalogSyncWorker._event(
            {
                "id": 1,
                "event_id": "event",
                "aggregate_type": "tool_websites",
                "aggregate_key": json.dumps([1]),
                "operation": "delete",
                "source_method": "test",
                "attempt_count": 1,
                "lease_token": "lease",
            }
        )


def test_barrier_claim_never_leases_events_above_fixed_id() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    worker = ProjectCatalogSyncWorker(
        TransactionalDatabase(connection),  # type: ignore[arg-type]
        writer=MagicMock(),
        batch_size=5,
    )

    assert worker.claim(barrier_id=12) == []

    sql, params = cursor.execute.call_args.args
    assert sql.count("id <= %s") == 2
    assert params == (12, 12, 5)


def test_capture_barrier_requires_capture_and_reads_fixed_max(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"barrier_id": 17}
    worker = ProjectCatalogSyncWorker(
        TransactionalDatabase(connection),  # type: ignore[arg-type]
        writer=MagicMock(),
    )
    monkeypatch.setattr(
        "backend.app.services.project_catalog_sync.settings.project_catalog_outbox_capture_enabled",
        True,
    )

    barrier = worker.capture_barrier()

    assert barrier.id == 17
    assert "MAX(id)" in cursor.execute.call_args.args[0]


def test_exact_barrier_proof_canonicalizes_json_key_order() -> None:
    mysql_connection = MagicMock()
    mysql_cursor = mysql_connection.cursor.return_value.__enter__.return_value
    mysql_cursor.fetchone.return_value = {
        "pending": 0,
        "leased": 0,
        "retry": 0,
        "processed": 1,
        "dead": 0,
    }
    mysql_cursor.fetchall.return_value = [
        {
            "id": 7,
            "event_id": "00000000-0000-0000-0000-000000000007",
            "aggregate_type": "github_repo_snapshots",
            "aggregate_key": '{"snapshot_date":"2026-07-24","repo_id":"r"}',
            "operation": "reconcile",
            "source_method": "test",
        }
    ]
    postgres_connection = MagicMock()
    postgres_cursor = postgres_connection.cursor.return_value.__enter__.return_value
    postgres_cursor.fetchall.return_value = [
        {
            "outbox_id": 7,
            "event_id": "00000000-0000-0000-0000-000000000007",
            "aggregate_type": "github_repo_snapshots",
            "aggregate_key": {"repo_id": "r", "snapshot_date": "2026-07-24"},
            "operation": "reconcile",
            "source_method": "test",
        }
    ]
    worker = ProjectCatalogSyncWorker(
        TransactionalDatabase(mysql_connection),  # type: ignore[arg-type]
        writer=MagicMock(),
        postgres=TransactionalDatabase(postgres_connection),  # type: ignore[arg-type]
    )

    proof = worker.prove_barrier(7)

    assert proof["barrier_proven"] is True
    assert proof["compared"] == 1
    assert proof["missing_applied"] == 0
    assert proof["extra_applied"] == 0


def test_barrier_proof_pages_past_duplicate_at_barrier_id() -> None:
    mysql_connection = MagicMock()
    mysql_cursor = mysql_connection.cursor.return_value.__enter__.return_value
    mysql_cursor.fetchone.return_value = {
        "pending": 0,
        "leased": 0,
        "retry": 0,
        "processed": 1,
        "dead": 0,
    }
    source = {
        "id": 1,
        "event_id": "00000000-0000-0000-0000-000000000001",
        "aggregate_type": "tool_websites",
        "aggregate_key": '{"id":1}',
        "operation": "reconcile",
        "source_method": "test",
    }
    mysql_cursor.fetchall.side_effect = [[source], []]
    postgres_connection = MagicMock()
    postgres_cursor = postgres_connection.cursor.return_value.__enter__.return_value
    first = {
        **source,
        "outbox_id": 1,
        "aggregate_key": {"id": 1},
    }
    first.pop("id")
    duplicate = {
        **first,
        "event_id": "00000000-0000-0000-0000-000000000002",
    }
    postgres_cursor.fetchall.side_effect = [[first], [duplicate], []]
    worker = ProjectCatalogSyncWorker(
        TransactionalDatabase(mysql_connection),  # type: ignore[arg-type]
        writer=MagicMock(),
        postgres=TransactionalDatabase(postgres_connection),  # type: ignore[arg-type]
    )

    proof = worker.prove_barrier(1, page_size=1)

    assert proof["barrier_proven"] is False
    assert proof["duplicate_outbox_ids"] == 1
    assert postgres_cursor.execute.call_count == 3


def test_barrier_proof_detects_missing_middle_event_without_miscounting_tail() -> None:
    mysql_connection = MagicMock()
    mysql_cursor = mysql_connection.cursor.return_value.__enter__.return_value
    mysql_cursor.fetchone.return_value = {
        "pending": 0,
        "leased": 0,
        "retry": 0,
        "processed": 2,
        "dead": 0,
    }
    base = {
        "aggregate_type": "tool_websites",
        "aggregate_key": '{"id":1}',
        "operation": "reconcile",
        "source_method": "test",
    }
    mysql_cursor.fetchall.return_value = [
        {**base, "id": 1, "event_id": "00000000-0000-0000-0000-000000000001"},
        {**base, "id": 2, "event_id": "00000000-0000-0000-0000-000000000002"},
    ]
    postgres_connection = MagicMock()
    postgres_cursor = postgres_connection.cursor.return_value.__enter__.return_value
    postgres_cursor.fetchall.return_value = [
        {
            **base,
            "aggregate_key": {"id": 1},
            "outbox_id": 2,
            "event_id": "00000000-0000-0000-0000-000000000002",
        }
    ]
    worker = ProjectCatalogSyncWorker(
        TransactionalDatabase(mysql_connection),  # type: ignore[arg-type]
        writer=MagicMock(),
        postgres=TransactionalDatabase(postgres_connection),  # type: ignore[arg-type]
    )

    proof = worker.prove_barrier(2)

    assert proof["barrier_proven"] is False
    assert proof["missing_applied"] == 1
    assert proof["compared"] == 1
