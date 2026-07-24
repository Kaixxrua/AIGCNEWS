from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from scripts import migrate_mysql_catalog_schema


def test_parser_has_no_database_credentials() -> None:
    parser = migrate_mysql_catalog_schema.build_parser()
    options = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    assert "--password" not in options
    assert "--dsn" not in options


def test_apply_without_flag_is_dry_run(capsys) -> None:
    runner = MagicMock()
    runner.status.return_value = []
    with (
        patch.object(migrate_mysql_catalog_schema, "MySQLMigrationRunner", return_value=runner),
        patch.object(migrate_mysql_catalog_schema.mysql_database, "close"),
    ):
        code = migrate_mysql_catalog_schema.main(["apply"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "dry_run"
    runner.apply.assert_not_called()


def test_failures_are_sanitized(capsys) -> None:
    runner = MagicMock()
    runner.status.side_effect = RuntimeError("mysql://user:secret@database/catalog")
    with (
        patch.object(migrate_mysql_catalog_schema, "MySQLMigrationRunner", return_value=runner),
        patch.object(migrate_mysql_catalog_schema.mysql_database, "close"),
    ):
        code = migrate_mysql_catalog_schema.main(["status"])
    output = capsys.readouterr()
    assert code == 1
    assert "RuntimeError" in output.err
    assert "secret" not in output.err
