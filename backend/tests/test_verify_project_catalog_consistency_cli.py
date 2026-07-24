from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from scripts import verify_project_catalog_consistency


def test_parser_does_not_accept_database_credentials() -> None:
    parser = verify_project_catalog_consistency.build_parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    assert "--dsn" not in option_strings
    assert "--password" not in option_strings


def test_matching_stable_report_exits_successfully(capsys) -> None:
    service = MagicMock()
    service.verify.return_value = {"status": "match", "stable": True}
    with (
        patch.object(
            verify_project_catalog_consistency,
            "ProjectCatalogConsistencyService",
            return_value=service,
        ),
        patch.object(verify_project_catalog_consistency.postgres_database, "close") as close,
    ):
        code = verify_project_catalog_consistency.main(
            [
                "--target-database",
                "catalog_test",
                "--target-schema",
                "public",
            ]
        )
    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "match"
    close.assert_called_once_with()


def test_failures_do_not_print_secret_bearing_messages(capsys) -> None:
    service = MagicMock()
    service.verify.side_effect = RuntimeError(
        "postgresql://user:super-secret@database/catalog"
    )
    with (
        patch.object(
            verify_project_catalog_consistency,
            "ProjectCatalogConsistencyService",
            return_value=service,
        ),
        patch.object(verify_project_catalog_consistency.postgres_database, "close"),
    ):
        code = verify_project_catalog_consistency.main(
            [
                "--target-database",
                "catalog_test",
                "--target-schema",
                "public",
            ]
        )
    output = capsys.readouterr()
    assert code == 1
    assert "RuntimeError" in output.err
    assert "super-secret" not in output.err
