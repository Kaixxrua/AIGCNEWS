from __future__ import annotations

import json
from unittest.mock import patch

from scripts import inventory_mysql_schema


def _artifact(*, ready: bool) -> dict[str, object]:
    return {
        "artifact_version": 1,
        "artifact_sha256": "a" * 64,
        "summary": {
            "ready_for_schema_design": ready,
            "table_count": 1,
            "unknown_tables": [] if ready else ["unknown_table"],
        },
        "tables": [],
    }


def test_parser_exposes_no_database_credentials_or_mutations() -> None:
    parser = inventory_mysql_schema.build_parser()
    options = {option for action in parser._actions for option in action.option_strings}

    assert "--password" not in options
    assert "--dsn" not in options
    assert "--apply" not in options
    assert "--output" in options


def test_cli_writes_ready_inventory(tmp_path, capsys) -> None:
    output = tmp_path / "inventory.json"
    service = type("Service", (), {"collect": lambda self, exact_counts: _artifact(ready=True)})()
    with (
        patch.object(inventory_mysql_schema, "MySQLSchemaInventoryService", return_value=service),
        patch.object(inventory_mysql_schema.mysql_database, "close") as close,
    ):
        code = inventory_mysql_schema.main(["--output", str(output)])

    assert code == 0
    assert json.loads(output.read_text(encoding="utf-8"))["artifact_version"] == 1
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
    close.assert_called_once_with()


def test_cli_returns_review_required_for_unknown_tables(tmp_path, capsys) -> None:
    output = tmp_path / "inventory.json"
    service = type("Service", (), {"collect": lambda self, exact_counts: _artifact(ready=False)})()
    with (
        patch.object(inventory_mysql_schema, "MySQLSchemaInventoryService", return_value=service),
        patch.object(inventory_mysql_schema.mysql_database, "close"),
    ):
        code = inventory_mysql_schema.main(
            ["--output", str(output), "--estimated-counts"]
        )

    assert code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "review_required"


def test_cli_failure_does_not_print_secret(tmp_path, capsys) -> None:
    service = type(
        "Service",
        (),
        {"collect": lambda self, exact_counts: (_ for _ in ()).throw(RuntimeError("mysql://root:secret@db"))},
    )()
    with (
        patch.object(inventory_mysql_schema, "MySQLSchemaInventoryService", return_value=service),
        patch.object(inventory_mysql_schema.mysql_database, "close"),
    ):
        code = inventory_mysql_schema.main(["--output", str(tmp_path / "unused.json")])

    captured = capsys.readouterr()
    assert code == 1
    assert "RuntimeError" in captured.err
    assert "secret" not in captured.err
