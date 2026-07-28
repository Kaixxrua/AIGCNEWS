from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

from backend.app.repositories.postgres_user_account_repository import (
    PostgresUserAccountRepository,
)
from backend.app.repositories.user_account_repository import UserAccountRepository


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


def repository_with_cursor():
    cursor = MagicMock()
    database = FakeDatabase(cursor)
    return PostgresUserAccountRepository(database), database, cursor


def test_postgres_repository_exposes_combined_user_contract() -> None:
    repository, _, _ = repository_with_cursor()

    contract: UserAccountRepository = repository

    assert callable(contract.get_user_by_email)
    assert callable(contract.create_user_with_email)
    assert callable(contract.get_today_registered_user_count)


def test_account_reads_normalize_email_and_copy_rows() -> None:
    repository, database, cursor = repository_with_cursor()
    row = {"id": 42, "hashed_password": "internal-hash"}
    cursor.fetchone.return_value = row

    result = repository.get_user_by_email("Reader@Example.COM")

    assert result == row
    assert result is not row
    assert cursor.execute.call_args.args[1] == ("reader@example.com",)
    assert database.transaction_count == 1


def test_create_users_use_returning_and_preserve_defaults() -> None:
    repository, database, cursor = repository_with_cursor()
    cursor.fetchone.side_effect = [{"id": 42}, {"id": 43}]

    phone_id = repository.create_user("13800000000", "reader", "hash")
    email_id = repository.create_user_with_email("Reader@Example.COM", "hash")

    assert (phone_id, email_id) == (42, 43)
    phone_call, email_call = cursor.execute.call_args_list
    assert "RETURNING id" in phone_call.args[0]
    assert phone_call.args[1] == ("13800000000", "reader", "hash", "user")
    assert "email_verified" in email_call.args[0]
    assert email_call.args[1] == ("reader@example.com", "", "hash", "user", "")
    assert database.transaction_count == 2


def test_password_update_is_owner_and_email_scoped() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.rowcount = 1

    affected = repository.update_user_password(
        user_id=42,
        email="Reader@Example.COM",
        hashed_password="new-hash",
    )

    assert affected == 1
    sql, params = cursor.execute.call_args.args
    assert "WHERE id = %s AND email = %s" in sql
    assert params == ("new-hash", 42, "reader@example.com")


def test_today_count_uses_shanghai_date_boundary() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchone.return_value = {"cnt": 2}

    with patch(
        "backend.app.repositories.postgres_user_account_repository.datetime"
    ) as datetime_type:
        datetime_type.now.return_value.date.return_value = date(2026, 7, 28)
        result = repository.get_today_registered_user_count()

    assert result == 2
    sql, params = cursor.execute.call_args.args
    assert "AT TIME ZONE 'Asia/Shanghai'" in sql
    assert params == (date(2026, 7, 28),)


def test_missing_insert_id_is_rejected() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchone.return_value = None

    try:
        repository.create_user("13800000000", "reader", "hash")
    except RuntimeError as error:
        assert "did not return an id" in str(error)
    else:
        raise AssertionError("missing RETURNING row should fail")
