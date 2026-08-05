from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from backend.app.repositories.postgres_x_credentials_repository import (
    PostgresXCredentialRepository,
)
from backend.app.repositories.x_credentials_repository import XCredentialRepository


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


def repository_with_cursor(bootstrap=None):
    cursor = MagicMock()
    database = FakeDatabase(cursor)
    return PostgresXCredentialRepository(database, bootstrap), database, cursor


def test_postgres_adapter_exposes_credential_contract() -> None:
    repository, _, _ = repository_with_cursor()
    contract: XCredentialRepository = repository

    assert callable(contract.list_x_credentials)
    assert callable(contract.get_x_credential)
    assert callable(contract.list_enabled_x_credentials)
    assert callable(contract.create_x_credential)
    assert callable(contract.update_x_credential)
    assert callable(contract.delete_x_credential)
    assert callable(contract.update_x_credential_test_result)


def test_seed_bootstraps_only_when_table_and_state_empty() -> None:
    repository, database, cursor = repository_with_cursor(
        (" auth-token ", " ct0-token ")
    )
    cursor.fetchone.side_effect = [None, {"n": 0}, {"id": 1}]
    cursor.fetchall.return_value = [{"id": 1, "display_name": "env-bootstrap"}]

    result = repository.list_x_credentials()

    (
        advisory_lock,
        bootstrap_select,
        count_query,
        insert,
        state_insert,
        listing,
    ) = cursor.execute.call_args_list
    assert "pg_advisory_xact_lock" in advisory_lock.args[0]
    assert "x_credentials_bootstrap_state" in bootstrap_select.args[0]
    assert "COUNT(*)" in count_query.args[0]
    assert "INSERT INTO x_credentials" in insert.args[0]
    assert insert.args[1] == (
        "env-bootstrap",
        "由环境变量初始化；请在 Monitor 的 X 凭证池中管理。",
        "auth-token",
        "ct0-token",
    )
    assert "x_credentials_bootstrap_state" in state_insert.args[0]
    assert result == [{"id": 1, "display_name": "env-bootstrap"}]
    assert database.transaction_count == 2


def test_seed_is_skipped_when_bootstrap_state_exists() -> None:
    repository, _, cursor = repository_with_cursor(("auth-token", "ct0-token"))
    cursor.fetchone.return_value = {"singleton_key": 1}
    cursor.fetchall.return_value = [{"id": 2, "display_name": "manual"}]

    result = repository.list_x_credentials()

    advisory_lock, state_select, listing = cursor.execute.call_args_list
    assert "pg_advisory_xact_lock" in advisory_lock.args[0]
    assert "x_credentials_bootstrap_state" in state_select.args[0]
    assert "INSERT" not in listing.args[0]
    assert result == [{"id": 2, "display_name": "manual"}]


def test_seed_records_state_when_existing_rows_but_no_state() -> None:
    repository, _, cursor = repository_with_cursor(("auth-token", "ct0-token"))
    cursor.fetchone.side_effect = [None, {"n": 5}]
    cursor.fetchall.return_value = [{"id": 1}]

    repository.list_x_credentials()

    _, _, count_query, state_insert, _ = cursor.execute.call_args_list
    assert "x_credentials_bootstrap_state" in state_insert.args[0]
    assert "INSERT" not in count_query.args[0]


def test_seed_is_skipped_without_bootstrap() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchall.return_value = [{"id": 1}]

    repository.list_x_credentials()

    assert cursor.execute.call_count == 1
    assert (
        "x_credentials_bootstrap_state"
        not in cursor.execute.call_args_list[0].args[0]
    )


def test_create_requires_complete_secret_pair() -> None:
    repository, _, _ = repository_with_cursor()

    with pytest.raises(ValueError, match="auth_token"):
        repository.create_x_credential({"auth_token": "", "ct0": "ct0"})

    with pytest.raises(ValueError, match="ct0"):
        repository.create_x_credential({"auth_token": "auth", "ct0": "  "})


def test_create_persists_and_returns_row() -> None:
    repository, _, cursor = repository_with_cursor()
    created = {"id": 42, "display_name": "Primary"}
    cursor.fetchone.side_effect = [{"id": 42}, created]

    result = repository.create_x_credential(
        {
            "display_name": " Primary ",
            "note": " main ",
            "auth_token": " auth ",
            "ct0": " ct0 ",
            "enabled": False,
            "sort_order": "3",
        }
    )

    insert, _refetch = cursor.execute.call_args_list
    assert "RETURNING id" in insert.args[0]
    assert insert.args[1] == ("Primary", "main", "auth", "ct0", False, 3)
    assert result == created


def test_update_retains_existing_secrets_when_blank() -> None:
    repository, _, cursor = repository_with_cursor()
    existing = {
        "id": 42,
        "display_name": "Old",
        "note": "old note",
        "auth_token": "old-auth",
        "ct0": "old-ct0",
        "enabled": True,
        "sort_order": 1,
    }
    updated = {**existing, "display_name": "New"}
    cursor.fetchone.side_effect = [existing, updated]

    result = repository.update_x_credential(42, {"display_name": " New "})

    _select, update, _refetch = cursor.execute.call_args_list
    assert update.args[1][:2] == ("New", "old note")
    assert update.args[1][2] == "old-auth"
    assert update.args[1][3] == "old-ct0"
    assert result == updated


def test_update_returns_none_when_missing() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchone.return_value = None

    assert repository.update_x_credential(99, {"display_name": "x"}) is None
    assert cursor.execute.call_count == 1


def test_update_rejects_blank_pair_when_existing_secrets_are_missing() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchone.return_value = {
        "id": 42,
        "display_name": "Bad",
        "auth_token": "",
        "ct0": "",
    }

    with pytest.raises(ValueError, match="auth_token"):
        repository.update_x_credential(42, {"display_name": "x"})


def test_update_retains_existing_secrets_and_accepts_complete_replacement() -> None:
    repository, _, cursor = repository_with_cursor()
    existing = {
        "id": 42,
        "display_name": "Old",
        "note": "old note",
        "auth_token": "old-auth",
        "ct0": "old-ct0",
        "enabled": True,
        "sort_order": 1,
    }
    updated = {**existing, "display_name": "New"}
    cursor.fetchone.side_effect = [existing, updated]

    result = repository.update_x_credential(
        42,
        {"display_name": " New ", "auth_token": "new-auth", "ct0": "new-ct0"},
    )

    _select, update, _refetch = cursor.execute.call_args_list
    assert update.args[1][:2] == ("New", "old note")
    assert update.args[1][2] == "new-auth"
    assert update.args[1][3] == "new-ct0"
    assert result == updated


def test_delete_reports_rowcount() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.rowcount = 1
    assert repository.delete_x_credential(42) is True
    cursor.rowcount = 0
    assert repository.delete_x_credential(42) is False


def test_update_test_result_persists_status_message() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.rowcount = 1
    row = {"id": 42, "last_test_status": "failed"}
    cursor.fetchone.return_value = row

    result = repository.update_x_credential_test_result(
        42, {"status": " SUCCEEDED ", "message": " OK "}
    )

    update = cursor.execute.call_args_list[0]
    assert "last_test_at = CURRENT_TIMESTAMP" in update.args[0]
    assert update.args[1] == ("succeeded", "OK", 42)
    assert result == row


def test_update_test_result_returns_none_when_row_missing() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.rowcount = 0

    assert repository.update_x_credential_test_result(99, {"status": "failed"}) is None


def test_list_enabled_x_credentials_orders_by_sort_order_then_id() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchall.return_value = [{"id": 1}]

    repository.list_enabled_x_credentials()

    listing = cursor.execute.call_args_list[0]
    assert "WHERE enabled" in listing.args[0]
    assert "ORDER BY sort_order ASC, id ASC" in listing.args[0]


def test_list_x_credentials_orders_by_enabled_then_sort_order() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchall.return_value = [{"id": 1}]

    repository.list_x_credentials()

    listing = cursor.execute.call_args_list[0]
    assert "ORDER BY enabled DESC, sort_order ASC, id ASC" in listing.args[0]
