from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from backend.app.repositories.email_pool_settings_repository import (
    EmailPoolSettings,
    EmailPoolSettingsRepository,
)
from backend.app.repositories.postgres_email_pool_settings_repository import (
    PostgresEmailPoolSettingsRepository,
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
    return PostgresEmailPoolSettingsRepository(database), database, cursor


def _settings_row(**overrides):
    row = {
        "entries": '[{"name":"brevo","host":"smtp-relay.brevo.test"}]',
        "updated_at": datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def test_adapter_exposes_email_pool_settings_repository_contract() -> None:
    repository, _, _ = _make_repository()
    contract: EmailPoolSettingsRepository = repository

    assert callable(contract.get_email_pool_settings)
    assert callable(contract.upsert_email_pool_settings)
    assert callable(contract.delete_email_pool_settings)


def test_get_returns_none_when_singleton_row_missing() -> None:
    repository, _, cursor = _make_repository()
    cursor.fetchone.return_value = None

    assert repository.get_email_pool_settings() is None
    query = cursor.execute.call_args.args[0]
    assert "FROM email_pool_settings" in query
    assert "WHERE id = 1" in query


def test_get_maps_row_to_settings() -> None:
    repository, _, cursor = _make_repository()
    cursor.fetchone.return_value = _settings_row()

    result = repository.get_email_pool_settings()

    assert result == EmailPoolSettings(
        entries_json='[{"name":"brevo","host":"smtp-relay.brevo.test"}]',
        updated_at=datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc),
    )


def test_upsert_inserts_singleton_row_with_on_conflict() -> None:
    repository, database, cursor = _make_repository()
    cursor.fetchone.return_value = _settings_row()

    result = repository.upsert_email_pool_settings(
        entries_json='  [{"name":"brevo","host":"smtp-relay.brevo.test"}]  '
    )

    assert result.entries_json == '[{"name":"brevo","host":"smtp-relay.brevo.test"}]'
    query, params = cursor.execute.call_args.args
    assert "INSERT INTO email_pool_settings" in query
    assert "VALUES (1, %s, CURRENT_TIMESTAMP)" in query
    assert "ON CONFLICT (id) DO UPDATE" in query
    assert "RETURNING" in query
    # 入参经 strip 后落库
    assert params == ('[{"name":"brevo","host":"smtp-relay.brevo.test"}]',)
    assert database.transaction_count == 1


def test_upsert_accepts_empty_entries() -> None:
    # 空串合法：清空 DB 覆盖内容的语义由服务层 delete 承担，
    # 仓储层仅保证非空时恒为 JSON 数组
    repository, _, cursor = _make_repository()
    cursor.fetchone.return_value = _settings_row(entries="")

    result = repository.upsert_email_pool_settings(entries_json="")

    assert result.entries_json == ""
    assert cursor.execute.call_args.args[1] == ("",)


def test_upsert_rejects_non_json_and_non_list_payloads() -> None:
    repository, _, cursor = _make_repository()

    with pytest.raises(ValueError, match="JSON"):
        repository.upsert_email_pool_settings(entries_json="{broken")
    with pytest.raises(ValueError, match="JSON"):
        repository.upsert_email_pool_settings(entries_json='{"name":"brevo"}')
    cursor.execute.assert_not_called()


def test_delete_removes_singleton_row_and_returns_rowcount() -> None:
    repository, _, cursor = _make_repository()
    cursor.rowcount = 1

    assert repository.delete_email_pool_settings() == 1
    query = cursor.execute.call_args.args[0]
    assert "DELETE FROM email_pool_settings" in query
    assert "WHERE id = 1" in query
