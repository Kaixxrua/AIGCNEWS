from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from scripts import repair_project_catalog_sequences


def test_parser_does_not_accept_database_credentials() -> None:
    parser = repair_project_catalog_sequences.build_parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    assert "--dsn" not in option_strings
    assert "--password" not in option_strings


def test_default_is_dry_run(capsys) -> None:
    service = MagicMock()
    service.repair.return_value = {"status": "ready", "applied": False, "tables": []}
    with (
        patch.object(
            repair_project_catalog_sequences,
            "ProjectCatalogSequenceService",
            return_value=service,
        ),
        patch.object(repair_project_catalog_sequences.postgres_database, "close"),
    ):
        code = repair_project_catalog_sequences.main(
            ["--target-database", "catalog_test", "--target-schema", "public"]
        )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False
    assert service.repair.call_args.kwargs["apply"] is False


def test_failures_do_not_print_secret_bearing_messages(capsys) -> None:
    service = MagicMock()
    service.repair.side_effect = RuntimeError(
        "postgresql://user:super-secret@database/catalog"
    )
    with (
        patch.object(
            repair_project_catalog_sequences,
            "ProjectCatalogSequenceService",
            return_value=service,
        ),
        patch.object(repair_project_catalog_sequences.postgres_database, "close"),
    ):
        code = repair_project_catalog_sequences.main(
            ["--target-database", "catalog_test", "--target-schema", "public"]
        )

    output = capsys.readouterr()
    assert code == 1
    assert "RuntimeError" in output.err
    assert "super-secret" not in output.err
