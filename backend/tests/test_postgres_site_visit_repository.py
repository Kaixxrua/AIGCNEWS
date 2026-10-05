from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock

from backend.app.repositories.postgres_site_visit_repository import (
    PostgresSiteVisitRepository,
)
from backend.app.repositories.site_visit_repository import (
    LandingVisits,
    PlatformVisits,
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
    assert callable(contract.record_automated_visit)
    assert callable(contract.get_visit_stats)
    assert callable(contract.get_platform_breakdown)
    assert callable(contract.record_landing)
    assert callable(contract.get_landing_breakdown)


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
    platform_sql, platform_params = cursor.execute.call_args_list[1].args
    assert "INSERT INTO site_visit_platform_days" in platform_sql
    assert "ON CONFLICT (day, platform) DO UPDATE" in platform_sql
    # 未传 platform 时落默认 other 桶
    assert platform_params == (date(2026, 8, 13), "other")
    assert "SUM(visits)" in cursor.execute.call_args_list[2].args[0]


def test_record_visit_writes_platform_bucket_in_same_transaction() -> None:
    repository, database, cursor = _make_repository()
    cursor.fetchone.side_effect = [{"visits": 1}, {"total": 1}]

    repository.record_visit(date(2026, 8, 22), platform="ios")

    assert database.transaction_count == 1
    platform_sql, platform_params = cursor.execute.call_args_list[1].args
    assert "INSERT INTO site_visit_platform_days" in platform_sql
    assert platform_params == (date(2026, 8, 22), "ios")


def test_record_automated_visit_only_touches_platform_table() -> None:
    repository, database, cursor = _make_repository()

    assert repository.record_automated_visit(date(2026, 9, 29)) is None

    assert database.transaction_count == 1
    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args.args
    assert "INSERT INTO site_visit_platform_days" in sql
    assert "ON CONFLICT (day, platform) DO UPDATE" in sql
    assert "site_visit_days " not in sql
    assert params == (date(2026, 9, 29), "bot")


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


def test_get_platform_breakdown_with_window_lower_bound() -> None:
    repository, database, cursor = _make_repository()
    cursor.fetchall.return_value = [
        {"platform": "ios", "visits": 12},
        {"platform": "windows", "visits": 3},
    ]

    result = repository.get_platform_breakdown(date(2026, 8, 16))

    assert result == [
        PlatformVisits(platform="ios", visits=12),
        PlatformVisits(platform="windows", visits=3),
    ]
    assert database.transaction_count == 1
    sql, params = cursor.execute.call_args.args
    assert "FROM site_visit_platform_days" in sql
    assert "GROUP BY platform" in sql
    assert params == (date(2026, 8, 16), date(2026, 8, 16))


def test_get_platform_breakdown_all_time_passes_none_bound() -> None:
    repository, _, cursor = _make_repository()
    cursor.fetchall.return_value = []

    assert repository.get_platform_breakdown(None) == []
    sql, params = cursor.execute.call_args.args
    assert "%s::date IS NULL" in sql
    assert params == (None, None)


def test_record_landing_upserts_day_source_path_row() -> None:
    repository, database, cursor = _make_repository()

    assert repository.record_landing(date(2026, 10, 5), "mcp-429-anon", "/mcp") is None

    assert database.transaction_count == 1
    cursor.execute.assert_called_once()
    sql, params = cursor.execute.call_args.args
    assert "INSERT INTO site_landing_days" in sql
    assert "ON CONFLICT (day, source, path) DO UPDATE" in sql
    assert "landings = site_landing_days.landings + 1" in sql
    # 落地只写落地表，访问量两张表不动
    assert "site_visit_days" not in sql
    assert "site_visit_platform_days" not in sql
    assert params == (date(2026, 10, 5), "mcp-429-anon", "/mcp")


def test_get_landing_breakdown_aggregates_inclusive_window() -> None:
    repository, database, cursor = _make_repository()
    cursor.fetchall.return_value = [
        {"source": "mcp-429-anon", "path": "/mcp", "landings": 4},
        {"source": "api-429-daily", "path": "/membership", "landings": 1},
    ]

    result = repository.get_landing_breakdown(date(2026, 9, 22), date(2026, 10, 5))

    assert result == [
        LandingVisits(source="mcp-429-anon", path="/mcp", landings=4),
        LandingVisits(source="api-429-daily", path="/membership", landings=1),
    ]
    assert database.transaction_count == 1
    sql, params = cursor.execute.call_args.args
    assert "FROM site_landing_days" in sql
    assert "WHERE day BETWEEN %s AND %s" in sql
    assert "GROUP BY source, path" in sql
    assert params == (date(2026, 9, 22), date(2026, 10, 5))
