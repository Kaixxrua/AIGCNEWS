from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from scripts import migrate_mysql_to_postgres


def test_parser_does_not_accept_database_credentials() -> None:
    parser = migrate_mysql_to_postgres.build_parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    assert "--dsn" not in option_strings
    assert "--password" not in option_strings


def test_plan_prints_machine_readable_result(capsys) -> None:
    service = MagicMock()
    service.plan_catalog.return_value = {"status": "dry_run", "source_count": 2}
    with (
        patch.object(migrate_mysql_to_postgres, "ProjectCatalogTransferService", return_value=service),
        patch.object(migrate_mysql_to_postgres.postgres_database, "close") as close,
    ):
        code = migrate_mysql_to_postgres.main(
            [
                "plan",
                "--job-id",
                "job",
                "--target-database",
                "catalog_test",
                "--target-schema",
                "public",
            ]
        )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "dry_run"
    close.assert_called_once_with()


def test_failures_are_sanitized_to_error_class(capsys) -> None:
    service = MagicMock()
    service.status.side_effect = RuntimeError(
        "postgresql://user:super-secret@database/catalog"
    )
    with (
        patch.object(migrate_mysql_to_postgres, "ProjectCatalogTransferService", return_value=service),
        patch.object(migrate_mysql_to_postgres.postgres_database, "close"),
    ):
        code = migrate_mysql_to_postgres.main(["status", "--job-id", "job"])
    output = capsys.readouterr()
    assert code == 1
    assert "RuntimeError" in output.err
    assert "super-secret" not in output.err
