from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.app.services.application_data_transfer import (
    APPLICATION_TABLE_TRANSFER_BY_NAME,
    APPLICATION_TABLE_TRANSFER_SPECS,
)
from backend.app.services.application_transfer_service import ApplicationTransferService
from backend.app.services.project_catalog_transfer import (
    ProjectCatalogTransferSafetyError,
    TableCheckpoint,
)


class BatchCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.executemany_calls: list[tuple[str, object]] = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def execute(self, sql, params=None) -> None:
        self.calls.append((sql, params))

    def executemany(self, sql, params) -> None:
        self.executemany_calls.append((sql, params))


class Transaction:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def __enter__(self):
        self.events.append("begin")

    def __exit__(self, exc_type, exc, traceback):
        self.events.append("rollback" if exc_type else "commit")
        return False


class BatchConnection:
    def __init__(self, cursor: BatchCursor) -> None:
        self._cursor = cursor
        self.events: list[str] = []

    def transaction(self):
        return Transaction(self.events)

    def cursor(self):
        return self._cursor


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        app_env="test",
        mysql_host="mysql",
        mysql_port=3306,
        mysql_database="aigc_news",
        mysql_user="app",
    )


def service() -> ApplicationTransferService:
    return ApplicationTransferService(
        mysql=object(),
        postgres=object(),
        config=settings(),
    )  # type: ignore[arg-type]


def test_application_service_uses_all_specs_and_schema_version_six() -> None:
    transfer = service()

    assert transfer._table_specs == APPLICATION_TABLE_TRANSFER_SPECS
    assert transfer._minimum_schema_version == 6


def test_application_json_codec_normalizes_objects_and_preserves_valid_text() -> None:
    spec = APPLICATION_TABLE_TRANSFER_BY_NAME["chat_messages"]
    row = {column: None for column in spec.columns}
    row.update(
        {
            "id": 1,
            "conversation_id": 2,
            "role": "assistant",
            "content": "answer",
            "sources_json": {"b": 2, "a": 1},
            "attachments_json": "[]",
            "status": "done",
            "created_at": datetime(2026, 1, 1),
            "updated_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
        }
    )

    encoded = service()._encode_source_row(spec, row, source_timezone="UTC")

    assert encoded["sources_json"] == '{"a":1,"b":2}'
    assert encoded["attachments_json"] == "[]"
    assert encoded["created_at"] == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_application_json_codec_rejects_invalid_json() -> None:
    spec = APPLICATION_TABLE_TRANSFER_BY_NAME["chat_attachments"]
    row = {column: None for column in spec.columns}
    row.update({"id": 1, "user_id": 1, "meta_json": "not-json"})

    with pytest.raises(ProjectCatalogTransferSafetyError, match="invalid JSON"):
        service()._encode_source_row(spec, row, source_timezone="UTC")


def test_application_batch_casts_jsonb_and_updates_checkpoint_atomically() -> None:
    cursor = BatchCursor()
    connection = BatchConnection(cursor)
    spec = APPLICATION_TABLE_TRANSFER_BY_NAME["chat_messages"]
    row = {column: None for column in spec.columns}
    row.update(
        {
            "id": 1,
            "conversation_id": 2,
            "role": "assistant",
            "content": "answer",
            "sources_json": json.dumps([{"id": "doc-1"}]),
            "attachments_json": "[]",
            "status": "done",
        }
    )

    checkpoint = service()._write_table_batch(
        connection,
        spec=spec,
        job_id="application-job",
        checkpoint=TableCheckpoint({}, 0, 0, "pending"),
        rows=[row],
    )

    insert_sql = cursor.executemany_calls[0][0]
    assert insert_sql.count("%s::jsonb") == 2
    assert "ON CONFLICT (id) DO UPDATE" in insert_sql
    assert "UPDATE project_catalog_migration_checkpoints" in cursor.calls[-1][0]
    assert connection.events == ["begin", "commit"]
    assert checkpoint.cursor == {"id": 1}
