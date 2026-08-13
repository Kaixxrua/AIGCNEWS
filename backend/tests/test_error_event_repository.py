from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

from backend.app.repositories.error_event_repository import (
    ErrorEventInsert,
    ErrorEventRepository,
)
from backend.app.repositories.postgres_error_event_repository import (
    PostgresErrorEventRepository,
)


class FakeDatabase:
    def __init__(self, cursor: MagicMock) -> None:
        self.cursor = cursor
        self.connection = MagicMock()
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        self.connection.cursor.return_value = cursor_context
        self.transaction_count = 0

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        yield self.connection


def _make_repository(cursor: MagicMock | None = None):
    cursor = cursor or MagicMock()
    database = FakeDatabase(cursor)
    return PostgresErrorEventRepository(database), database, cursor


def _insert(**overrides) -> ErrorEventInsert:
    payload = {
        "level": "ERROR",
        "logger_name": "backend.app.core.scheduler",
        "message": "ingestion failed",
        "exception_type": "OperationalError",
        "stack_trace": "Traceback ...",
        "occurred_at": datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc),
    }
    payload.update(overrides)
    return ErrorEventInsert(**payload)


def test_adapter_exposes_error_event_repository_contract() -> None:
    repository, _, _ = _make_repository()
    contract: ErrorEventRepository = repository

    assert callable(contract.insert_events)
    assert callable(contract.list_events)
    assert callable(contract.prune_older_than)


def test_insert_events_skips_empty_batch() -> None:
    repository, database, cursor = _make_repository()

    assert repository.insert_events([]) == 0
    assert database.transaction_count == 0
    cursor.executemany.assert_not_called()


def test_insert_events_writes_batch_with_coalesce_default() -> None:
    repository, database, cursor = _make_repository()
    cursor.rowcount = 2
    occurred_at = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)

    result = repository.insert_events(
        [
            _insert(occurred_at=occurred_at),
            # occurred_at=None 的行由 DB DEFAULT CURRENT_TIMESTAMP 兜底
            _insert(occurred_at=None, exception_type=None, stack_trace=None),
        ]
    )

    assert result == 2
    assert database.transaction_count == 1
    query, rows = cursor.executemany.call_args.args
    assert "INSERT INTO error_events" in query
    assert "COALESCE(%s, CURRENT_TIMESTAMP)" in query
    assert rows == [
        (
            occurred_at,
            "ERROR",
            "backend.app.core.scheduler",
            "ingestion failed",
            "OperationalError",
            "Traceback ...",
        ),
        (None, "ERROR", "backend.app.core.scheduler", "ingestion failed", None, None),
    ]


def test_list_events_returns_newest_first_pagination_envelope() -> None:
    repository, _, cursor = _make_repository()
    cursor.fetchone.return_value = {"cnt": 21}
    cursor.fetchall.return_value = [
        {"id": 21, "level": "ERROR", "message": "latest"},
        {"id": 20, "level": "CRITICAL", "message": "previous"},
    ]

    result = repository.list_events(page=3, page_size=7)

    assert result == {
        "items": [
            {"id": 21, "level": "ERROR", "message": "latest"},
            {"id": 20, "level": "CRITICAL", "message": "previous"},
        ],
        "total": 21,
        "page": 3,
        "page_size": 7,
    }
    count_query = cursor.execute.call_args_list[0].args[0]
    page_query, page_params = cursor.execute.call_args_list[1].args
    assert "COUNT(*)" in count_query
    assert "ORDER BY id DESC" in page_query
    # page=3 & page_size=7 → offset 14
    assert page_params == (7, 14)


def test_prune_older_than_deletes_before_cutoff() -> None:
    repository, database, cursor = _make_repository()
    cursor.rowcount = 5
    cutoff = datetime(2026, 7, 13, 0, 0, tzinfo=timezone.utc)

    assert repository.prune_older_than(cutoff) == 5
    assert database.transaction_count == 1
    query, params = cursor.execute.call_args.args
    assert "DELETE FROM error_events" in query
    assert "occurred_at < %s" in query
    assert params == (cutoff,)
