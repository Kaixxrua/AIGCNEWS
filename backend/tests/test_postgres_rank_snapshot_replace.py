from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from backend.app.repositories.postgres_rank_snapshot_repository import (
    PostgresRankSnapshotRepository,
)


class FakeCursor:
    def __init__(self) -> None:
        self.statements: list[tuple[str, Any]] = []
        self.batches: list[tuple[str, list[Any]]] = []
        self.rowcount = 0
        self.fail_on: str = ""

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        normalized = " ".join(sql.split())
        if self.fail_on and self.fail_on in normalized:
            raise RuntimeError("simulated SQL failure")
        self.statements.append((normalized, params))

    def executemany(self, sql: str, seq: Any) -> None:
        rows = list(seq)
        normalized = " ".join(sql.split())
        if self.fail_on and self.fail_on in normalized:
            raise RuntimeError("simulated SQL failure")
        self.batches.append((normalized, rows))
        self.rowcount = len(rows)


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor


class FakeDatabase:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor = cursor
        self.connection = FakeConnection(cursor)
        self.transaction_count = 0

    @contextmanager
    def transaction(self) -> Iterator[FakeConnection]:
        self.transaction_count += 1
        yield self.connection


def _snapshots() -> list[dict[str, Any]]:
    return [
        {"doc_id": "doc-b", "rank_in_period": 2, "raw_score": 9.0, "score": 8.0},
        {"doc_id": "doc-a", "rank_in_period": 1, "raw_score": 7.5, "score": 6.5},
    ]


def test_replace_channel_snapshots_runs_delete_upsert_and_sync_in_one_transaction() -> None:
    cursor = FakeCursor()
    database = FakeDatabase(cursor)
    repository = PostgresRankSnapshotRepository(database)  # type: ignore[arg-type]

    written = repository.replace_channel_snapshots(
        "2026-08-08", "arxiv_daily", _snapshots()
    )

    assert written == 2
    assert database.transaction_count == 1
    assert cursor.statements[0][0].startswith("DELETE FROM document_rank_snapshots")
    assert cursor.statements[0][1] == ("2026-08-08", "arxiv_daily")
    assert len(cursor.batches) == 1
    batch_sql, batch_rows = cursor.batches[0]
    assert "ON CONFLICT (doc_id, snapshot_date, source_channel) DO UPDATE" in batch_sql
    assert "LEAST(document_rank_snapshots.rank_in_period" in batch_sql
    assert "GREATEST(document_rank_snapshots.raw_score" in batch_sql
    assert [row[0] for row in batch_rows] == ["doc-b", "doc-a"]
    assert all(row[1] == "2026-08-08" and row[2] == "arxiv_daily" for row in batch_rows)
    # 批量跨 channel 分数同步在同一事务内随 upsert 一起提交
    sync_sql, sync_params = cursor.statements[-1]
    assert sync_sql.startswith("WITH aggregate AS")
    assert "GROUP BY doc_id" in sync_sql
    assert sync_params[0] == "2026-08-08"
    assert sync_params[1] == ["doc-a", "doc-b"]
    assert sync_params[2] == "2026-08-08"


def test_replace_channel_snapshots_empty_batch_only_deletes_in_one_transaction() -> None:
    cursor = FakeCursor()
    database = FakeDatabase(cursor)
    repository = PostgresRankSnapshotRepository(database)  # type: ignore[arg-type]

    written = repository.replace_channel_snapshots("2026-08-08", "arxiv_daily", [])

    assert written == 0
    assert database.transaction_count == 1
    assert len(cursor.statements) == 1
    assert cursor.statements[0][0].startswith("DELETE FROM document_rank_snapshots")
    assert cursor.batches == []


def test_replace_channel_snapshots_failure_aborts_the_single_transaction() -> None:
    cursor = FakeCursor()
    cursor.fail_on = "WITH aggregate AS"
    database = FakeDatabase(cursor)
    repository = PostgresRankSnapshotRepository(database)  # type: ignore[arg-type]

    try:
        repository.replace_channel_snapshots("2026-08-08", "arxiv_daily", _snapshots())
    except RuntimeError as exc:
        assert "simulated SQL failure" in str(exc)
    else:
        raise AssertionError("expected the aggregate sync failure to propagate")

    # delete 与 upsert 必须同事务回滚，绝不允许 delete 已提交而 upsert 未发生
    assert database.transaction_count == 1
