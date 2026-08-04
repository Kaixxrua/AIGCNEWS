from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from psycopg import errors

from backend.app.repositories.postgres_x_watch_repository import (
    PostgresXWatchAccountRepository,
    normalize_x_screen_name,
)
from backend.app.repositories.x_watch_repository import (
    XWatchAccountConflictError,
    XWatchAccountRepository,
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


def repository_with_cursor(*args):
    cursor = MagicMock()
    database = FakeDatabase(cursor)
    return PostgresXWatchAccountRepository(database, *args), database, cursor


def test_postgres_adapter_exposes_repository_contract() -> None:
    repository, _, _ = repository_with_cursor()

    contract: XWatchAccountRepository = repository

    assert callable(contract.list_enabled_x_handles)
    assert callable(contract.update_x_watch_test_result)


def test_normalize_x_screen_name_strips_at_and_case() -> None:
    assert normalize_x_screen_name(" @OpenAI ") == "openai"
    assert normalize_x_screen_name("AnthropicAI") == "anthropicai"
    assert normalize_x_screen_name("@@karpathy") == "karpathy"
    assert normalize_x_screen_name("  ") == ""
    assert normalize_x_screen_name(None) == ""
    assert normalize_x_screen_name(42) == ""


def test_seed_uses_conflict_handling_and_list_orders_enabled_first() -> None:
    repository, database, cursor = repository_with_cursor(
        (" @OpenAI ", "", "karpathy"),
    )
    row = {"id": 42, "screen_name": "openai", "enabled": True}
    cursor.fetchall.return_value = [row]

    result = repository.list_x_watch_accounts()

    assert cursor.execute.call_count == 3
    seed_openai, seed_karpathy, listing = cursor.execute.call_args_list
    assert "ON CONFLICT (screen_name) DO NOTHING" in seed_openai.args[0]
    assert seed_openai.args[1][0] == "openai"
    assert seed_karpathy.args[1][0] == "karpathy"
    assert "ORDER BY enabled DESC, sort_order ASC, screen_name ASC, id ASC" in listing.args[0]
    assert result == [row]
    assert result[0] is not row
    assert database.transaction_count == 2


def test_create_normalizes_screen_name_and_uses_returning() -> None:
    repository, _, cursor = repository_with_cursor()
    created = {"id": 42, "screen_name": "openai", "enabled": True}
    cursor.fetchone.side_effect = [{"id": 42}, created]

    result = repository.create_x_watch_account(
        {
            "screen_name": " @OpenAI ",
            "display_name": " OpenAI ",
            "note": " 官方账号 ",
            "sort_order": "3",
        }
    )

    insert, _fetch = cursor.execute.call_args_list
    assert "RETURNING id" in insert.args[0]
    assert insert.args[1] == ("openai", "OpenAI", "官方账号", True, 3)
    assert result == created


def test_create_maps_unique_violation_to_conflict_error() -> None:
    repository, _, cursor = repository_with_cursor()

    class FakeUniqueViolation(errors.UniqueViolation):
        @property
        def diag(self):
            return MagicMock(constraint_name="uq_x_watch_accounts_screen_name")

    cursor.execute.side_effect = FakeUniqueViolation("duplicate")

    with pytest.raises(XWatchAccountConflictError):
        repository.create_x_watch_account({"screen_name": "openai"})


def test_update_preserves_existing_values_and_normalizes() -> None:
    repository, _, cursor = repository_with_cursor()
    existing = {
        "id": 42,
        "screen_name": "openai",
        "display_name": "OpenAI",
        "note": "官方账号",
        "enabled": True,
        "sort_order": 1,
    }
    updated = {**existing, "enabled": False, "note": "暂停"}
    cursor.fetchone.side_effect = [existing, updated]

    result = repository.update_x_watch_account(42, {"enabled": False, "note": " 暂停 "})

    _select, update, _refetch = cursor.execute.call_args_list
    assert "updated_at = CURRENT_TIMESTAMP" in update.args[0]
    assert update.args[1] == ("openai", "OpenAI", "暂停", False, 1, 42)
    assert result == updated


def test_update_returns_none_when_missing() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.fetchone.return_value = None

    assert repository.update_x_watch_account(99, {"enabled": False}) is None
    # 仅有 get 的一次 SELECT；不存在时不应触发 UPDATE
    assert cursor.execute.call_count == 1
    assert "SELECT" in cursor.execute.call_args_list[0].args[0]


def test_delete_reports_rowcount() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.rowcount = 1
    assert repository.delete_x_watch_account(42) is True
    cursor.rowcount = 0
    assert repository.delete_x_watch_account(42) is False


def test_update_test_result_persists_status_message() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.rowcount = 1
    row = {"id": 42, "last_test_status": "failed"}
    cursor.fetchone.return_value = row

    result = repository.update_x_watch_test_result(
        42, {"status": " FAILED ", "message": " auth expired "}
    )

    update = cursor.execute.call_args_list[0]
    assert "last_test_at = CURRENT_TIMESTAMP" in update.args[0]
    assert update.args[1] == ("failed", "auth expired", 42)
    assert result == row


def test_update_test_result_returns_none_when_row_missing() -> None:
    repository, _, cursor = repository_with_cursor()
    cursor.rowcount = 0

    assert repository.update_x_watch_test_result(99, {"status": "failed"}) is None


def test_list_enabled_x_handles_filters_and_normalizes() -> None:
    repository, _, cursor = repository_with_cursor(("openai",))
    cursor.fetchall.return_value = [
        {"screen_name": " @OpenAI "},
        {"screen_name": "anthropicai"},
        {"screen_name": "  "},
    ]

    handles = repository.list_enabled_x_handles()

    seed, listing = cursor.execute.call_args_list
    assert "ON CONFLICT (screen_name) DO NOTHING" in seed.args[0]
    assert "WHERE enabled" in listing.args[0]
    assert "ORDER BY sort_order ASC, screen_name ASC, id ASC" in listing.args[0]
    assert handles == ["openai", "anthropicai"]
