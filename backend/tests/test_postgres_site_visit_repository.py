from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock

from backend.app.repositories.postgres_site_visit_repository import (
    PostgresSiteVisitRepository,
)
from backend.app.repositories.site_visit_repository import (
    SiteVisitRepository,
    SiteVisitStats,
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
    return PostgresSiteVisitRepository(database), database, cursor


def test_adapter_exposes_site_visit_repository_contract() -> None:
    repository, _, _ = _make_repository()
    contract: SiteVisitRepository = repository

    assert callable(contract.record_visit)
    assert callable(contract.get_visit_stats)


def test_record_visit_upserts_day_row_and_returns_fresh_counters() -> None:
    repository, database, cursor = _make_repository()
    cursor.fetchone.side_effect = [{"visits": 8}, {"total": 701}]

    result = repository.record_visit(date(2026, 8, 13))

    assert result == SiteVisitStats(today_visits=8, total_visits=701)
    assert database.transaction_count == 1
    upsert_sql, upsert_params = cursor.execute.call_args_list[0].args
    assert "INSERT INTO site_visit_days" in upsert_sql
    assert "ON CONFLICT (day) DO UPDATE" in upsert_sql
    assert upsert_params == (date(2026, 8, 13),)
    assert "SUM(visits)" in cursor.execute.call_args_list[1].args[0]


def test_record_visit_handles_empty_returning_row() -> None:
    repository, _, cursor = _make_repository()
    cursor.fetchone.side_effect = [None, None]

    assert repository.record_visit(date(2026, 8, 13)) == SiteVisitStats(
        today_visits=0, total_visits=0
    )


def test_get_visit_stats_maps_today_and_total_in_single_query() -> None:
    repository, database, cursor = _make_repository()
    cursor.fetchone.return_value = {"today_visits": 5, "total_visits": 99}

    result = repository.get_visit_stats(date(2026, 8, 13))

    assert result == SiteVisitStats(today_visits=5, total_visits=99)
    assert database.transaction_count == 1
    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args.args
    assert "WHERE day = %s" in sql
    assert "SUM(visits)" in sql
    assert params == (date(2026, 8, 13),)


def test_get_visit_stats_defaults_missing_day_to_zero() -> None:
    repository, _, cursor = _make_repository()
    cursor.fetchone.return_value = {"today_visits": None, "total_visits": 99}

    assert repository.get_visit_stats(date(2026, 8, 13)) == SiteVisitStats(
        today_visits=0, total_visits=99
    )


def test_get_visit_stats_tolerates_empty_result_row() -> None:
    repository, _, cursor = _make_repository()
    cursor.fetchone.return_value = None

    assert repository.get_visit_stats(date(2026, 8, 13)) == SiteVisitStats(
        today_visits=0, total_visits=0
    )
