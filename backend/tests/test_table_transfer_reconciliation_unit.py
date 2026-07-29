from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from backend.app.services.application_data_transfer import APPLICATION_TABLE_TRANSFER_BY_NAME
from backend.app.services.table_transfer_reconciliation import (
    TableTransferReconciliationService,
    TransferReconciliationError,
    canonical_row_bytes,
)
from scripts import verify_application_transfer


def test_reconciliation_canonical_digest_normalizes_bool_datetime_and_json() -> None:
    spec = APPLICATION_TABLE_TRANSFER_BY_NAME["chat_messages"]
    mysql_row = {
        "id": 7,
        "conversation_id": 2,
        "role": "assistant",
        "content": "ok",
        "thinking": None,
        "sources_json": '{"b":2,"a":true}',
        "attachments_json": "[]",
        "status": "done",
        "parent_message_id": None,
        "created_at": datetime(2026, 1, 2, 3, 4, 5),
        "updated_at": "2026-01-02T03:04:05Z",
    }
    postgres_row = dict(mysql_row)
    postgres_row.update(
        sources_json={"a": True, "b": 2},
        attachments_json=[],
        created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )
    assert canonical_row_bytes(spec, mysql_row) == canonical_row_bytes(spec, postgres_row)


def test_reconciliation_accepts_table_without_identity_column() -> None:
    spec = APPLICATION_TABLE_TRANSFER_BY_NAME["documents"]
    postgres = MagicMock()
    service = TableTransferReconciliationService(
        mysql=MagicMock(),
        postgres=postgres,
        table_specs=(spec,),
        check_foreign_keys=False,
    )
    digest = (1, "key-digest", "row-digest", None)

    with (
        patch.object(
            service,
            "_confirm_target",
            return_value=MagicMock(
                database="app_test",
                schema="public",
                schema_version=6,
            ),
        ),
        patch.object(service, "_require_terminal_checkpoints"),
        patch.object(service, "_digest_source", return_value=digest),
        patch.object(service, "_digest_target", return_value=digest),
    ):
        result = service.verify(
            job_id="complete-job",
            target_database="app_test",
            target_schema="public",
        )

    assert result["tables"][0]["identity"] == {"status": "not_applicable"}
    assert result["tables"][0]["status"] == "match"
    assert result["status"] == "match"


def test_reconciliation_rejects_invalid_json_without_exposing_value() -> None:
    spec = APPLICATION_TABLE_TRANSFER_BY_NAME["chat_messages"]
    with pytest.raises(TransferReconciliationError, match="invalid JSON") as raised:
        canonical_row_bytes(spec, {"sources_json": "secret{broken"})
    assert "secret" not in str(raised.value)


def test_application_verify_cli_requires_confirmations_and_redacts_errors(capsys) -> None:
    parser = verify_application_transfer.build_parser()
    options = {option for action in parser._actions for option in action.option_strings}
    assert {"--job-id", "--target-database", "--target-schema"} <= options
    assert "--dsn" not in options and "--password" not in options

    service = MagicMock()
    service.verify.side_effect = RuntimeError("postgresql://user:secret@db/app")
    with (
        patch.object(
            verify_application_transfer,
            "TableTransferReconciliationService",
            return_value=service,
        ),
        patch.object(verify_application_transfer.mysql_database, "close"),
        patch.object(verify_application_transfer.postgres_database, "close"),
    ):
        code = verify_application_transfer.main(
            [
                "--job-id",
                "complete-job",
                "--target-database",
                "app_test",
                "--target-schema",
                "public",
            ]
        )
    assert code == 1
    output = json.loads(capsys.readouterr().err)
    assert output == {"status": "failed", "error_class": "RuntimeError"}
