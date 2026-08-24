"""payment_plan_overrides PostgreSQL 仓储契约测试（仿 smtp 仓测替身模式）。

钉住：SQL 形状（表名/列清单/ON CONFLICT/RETURNING）、行→dataclass 映射、
upsert 边界复校（防御性，先于 SQL 执行抛 ValueError）、delete 返回 rowcount。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from backend.app.repositories.payment_plan_overrides_repository import (
    PaymentPlanOverride,
    PaymentPlanOverridesRepository,
)
from backend.app.repositories.postgres_payment_plan_overrides_repository import (
    PostgresPaymentPlanOverridesRepository,
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
    return PostgresPaymentPlanOverridesRepository(database), database, cursor


def _override_row(**overrides):
    row = {
        "plan_code": "member_monthly",
        "amount_cents": 2500,
        "updated_at": datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def test_adapter_exposes_payment_plan_overrides_contract() -> None:
    repository, _, _ = _make_repository()
    contract: PaymentPlanOverridesRepository = repository

    assert callable(contract.list_plan_overrides)
    assert callable(contract.upsert_plan_override)
    assert callable(contract.delete_plan_override)


def test_list_maps_rows_ordered_by_plan_code() -> None:
    repository, _, cursor = _make_repository()
    cursor.fetchall.return_value = [
        _override_row(),
        _override_row(plan_code="member_yearly", amount_cents=20000),
    ]

    result = repository.list_plan_overrides()

    assert result == (
        PaymentPlanOverride(
            plan_code="member_monthly",
            amount_cents=2500,
            updated_at=datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc),
        ),
        PaymentPlanOverride(
            plan_code="member_yearly",
            amount_cents=20000,
            updated_at=datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc),
        ),
    )
    query = cursor.execute.call_args.args[0]
    assert "FROM payment_plan_overrides" in query
    assert "ORDER BY plan_code" in query


def test_list_empty_table_returns_empty_tuple() -> None:
    repository, _, cursor = _make_repository()
    cursor.fetchall.return_value = []

    assert repository.list_plan_overrides() == ()


def test_upsert_rejects_out_of_bounds_before_sql() -> None:
    repository, _, cursor = _make_repository()

    for bad in (0, 99, 1000001):
        with pytest.raises(ValueError, match="100-1000000"):
            repository.upsert_plan_override(
                plan_code="member_monthly", amount_cents=bad
            )
    cursor.execute.assert_not_called()


def test_upsert_inserts_with_on_conflict_returning() -> None:
    repository, database, cursor = _make_repository()
    cursor.fetchone.return_value = _override_row(amount_cents=2500)

    result = repository.upsert_plan_override(
        plan_code="member_monthly", amount_cents=2500
    )

    assert result.amount_cents == 2500
    query, params = cursor.execute.call_args.args
    assert "INSERT INTO payment_plan_overrides" in query
    assert "VALUES (%s, %s, CURRENT_TIMESTAMP)" in query
    assert "ON CONFLICT (plan_code) DO UPDATE" in query
    assert "RETURNING" in query
    assert params == ("member_monthly", 2500)
    assert database.transaction_count == 1


def test_delete_returns_rowcount() -> None:
    repository, _, cursor = _make_repository()
    cursor.rowcount = 1

    assert repository.delete_plan_override("member_monthly") == 1
    query, params = cursor.execute.call_args.args
    assert "DELETE FROM payment_plan_overrides" in query
    assert "WHERE plan_code = %s" in query
    assert params == ("member_monthly",)


def test_delete_missing_row_returns_zero() -> None:
    repository, _, cursor = _make_repository()
    cursor.rowcount = 0

    assert repository.delete_plan_override("member_lifetime") == 0
