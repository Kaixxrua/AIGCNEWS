from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from backend.app.repositories.postgres_smtp_settings_repository import (
    PostgresSmtpSettingsRepository,
)
from backend.app.repositories.smtp_settings_repository import (
    SmtpSettings,
    SmtpSettingsRepository,
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
    return PostgresSmtpSettingsRepository(database), database, cursor


def _settings_row(**overrides):
    row = {
        "host": "smtp.example.test",
        "port": 465,
        "username": "smtp-user",
        "password": "smtp-password",
        "from_email": "sender@example.test",
        "from_name": "AIGC",
        "use_tls": True,
        "updated_at": datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def test_adapter_exposes_smtp_settings_repository_contract() -> None:
    repository, _, _ = _make_repository()
    contract: SmtpSettingsRepository = repository

    assert callable(contract.get_smtp_settings)
    assert callable(contract.upsert_smtp_settings)
    assert callable(contract.delete_smtp_settings)


def test_get_returns_none_when_singleton_row_missing() -> None:
    repository, _, cursor = _make_repository()
    cursor.fetchone.return_value = None

    assert repository.get_smtp_settings() is None
    query = cursor.execute.call_args.args[0]
    assert "FROM smtp_settings" in query
    assert "WHERE id = 1" in query


def test_get_maps_row_to_settings() -> None:
    repository, _, cursor = _make_repository()
    cursor.fetchone.return_value = _settings_row()

    result = repository.get_smtp_settings()

    assert result == SmtpSettings(
        host="smtp.example.test",
        port=465,
        username="smtp-user",
        password="smtp-password",
        from_email="sender@example.test",
        from_name="AIGC",
        use_tls=True,
        updated_at=datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc),
    )


def test_upsert_validates_port_range() -> None:
    repository, _, cursor = _make_repository()

    with pytest.raises(ValueError, match="port"):
        repository.upsert_smtp_settings(
            host="smtp.example.test",
            port=0,
            username="",
            password="",
            from_email="sender@example.test",
            from_name="",
            use_tls=True,
        )
    with pytest.raises(ValueError, match="port"):
        repository.upsert_smtp_settings(
            host="smtp.example.test",
            port=65536,
            username="",
            password="",
            from_email="sender@example.test",
            from_name="",
            use_tls=True,
        )
    cursor.execute.assert_not_called()


def test_upsert_inserts_singleton_row_with_on_conflict() -> None:
    repository, database, cursor = _make_repository()
    cursor.fetchone.return_value = _settings_row(host="smtp.saved.test", use_tls=False)

    result = repository.upsert_smtp_settings(
        host="  smtp.saved.test  ",
        port=587,
        username="user",
        password="secret",
        from_email="sender@example.test",
        from_name="AIGC",
        use_tls=False,
    )

    assert result.host == "smtp.saved.test"
    query, params = cursor.execute.call_args.args
    assert "INSERT INTO smtp_settings" in query
    assert "VALUES (1, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)" in query
    assert "ON CONFLICT (id) DO UPDATE" in query
    assert "RETURNING" in query
    # host 入参经 strip；全列非空兜底为空串
    assert params == (
        "smtp.saved.test",
        587,
        "user",
        "secret",
        "sender@example.test",
        "AIGC",
        False,
    )
    assert database.transaction_count == 1


def test_delete_removes_singleton_row_and_returns_rowcount() -> None:
    repository, _, cursor = _make_repository()
    cursor.rowcount = 1

    assert repository.delete_smtp_settings() == 1
    query = cursor.execute.call_args.args[0]
    assert "DELETE FROM smtp_settings" in query
    assert "WHERE id = 1" in query
