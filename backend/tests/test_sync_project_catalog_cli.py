from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from scripts import sync_project_catalog


def test_parser_has_no_database_credentials() -> None:
    parser = sync_project_catalog.build_parser()
    options = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    assert "--password" not in options
    assert "--dsn" not in options


def test_run_once_requires_apply_flag(capsys) -> None:
    worker = MagicMock()
    worker.status.return_value = {"pending": 2, "dead": 0}
    with (
        patch.object(sync_project_catalog, "ProjectCatalogReconciliationWriter"),
        patch.object(sync_project_catalog, "ProjectCatalogSyncWorker", return_value=worker),
        patch.object(sync_project_catalog.mysql_database, "close"),
        patch.object(sync_project_catalog.postgres_database, "close"),
    ):
        code = sync_project_catalog.main(["run-once"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["status"] == "dry_run"
    worker.run_once.assert_not_called()


def test_failures_are_sanitized(capsys) -> None:
    worker = MagicMock()
    worker.status.side_effect = RuntimeError("postgres://user:secret@database/catalog")
    with (
        patch.object(sync_project_catalog, "ProjectCatalogReconciliationWriter"),
        patch.object(sync_project_catalog, "ProjectCatalogSyncWorker", return_value=worker),
        patch.object(sync_project_catalog.mysql_database, "close"),
        patch.object(sync_project_catalog.postgres_database, "close"),
    ):
        code = sync_project_catalog.main(["status"])
    output = capsys.readouterr()
    assert code == 1
    assert "RuntimeError" in output.err
    assert "secret" not in output.err
