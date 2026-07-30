from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from scripts import repair_github_watcher_corruption


def test_parser_does_not_accept_database_credentials() -> None:
    parser = repair_github_watcher_corruption.build_parser()
    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    assert "--dsn" not in option_strings
    assert "--password" not in option_strings


def test_default_is_dry_run(capsys) -> None:
    service = MagicMock()
    service.repair.return_value = {
        "status": "ready",
        "applied": False,
        "matched": 0,
    }
    with (
        patch.object(
            repair_github_watcher_corruption,
            "GitHubWatcherCorruptionRepairService",
            return_value=service,
        ),
        patch.object(repair_github_watcher_corruption.postgres_database, "close"),
    ):
        code = repair_github_watcher_corruption.main(
            ["--target-database", "catalog_test", "--target-schema", "public"]
        )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False
    assert service.repair.call_args.kwargs["apply"] is False
    assert service.repair.call_args.kwargs["production_authorized"] is False


def test_apply_and_cursor_options_are_forwarded(capsys) -> None:
    service = MagicMock()
    service.repair.return_value = {
        "status": "ready",
        "applied": True,
        "matched": 1,
    }
    with (
        patch.object(
            repair_github_watcher_corruption,
            "GitHubWatcherCorruptionRepairService",
            return_value=service,
        ),
        patch.object(repair_github_watcher_corruption.postgres_database, "close"),
    ):
        code = repair_github_watcher_corruption.main(
            [
                "--target-database",
                "catalog_test",
                "--target-schema",
                "public",
                "--batch-size",
                "25",
                "--after-snapshot-date",
                "2026-07-01",
                "--after-repo-id",
                "acme/repo",
                "--apply",
                "--authorize-production",
            ]
        )

    assert code == 0
    kwargs = service.repair.call_args.kwargs
    assert kwargs["batch_size"] == 25
    assert kwargs["after_snapshot_date"] == "2026-07-01"
    assert kwargs["after_repo_id"] == "acme/repo"
    assert kwargs["apply"] is True
    assert kwargs["production_authorized"] is True
    assert json.loads(capsys.readouterr().out)["applied"] is True


def test_failures_do_not_print_secret_bearing_messages(capsys) -> None:
    service = MagicMock()
    service.repair.side_effect = RuntimeError(
        "postgresql://user:super-secret@database/catalog"
    )
    with (
        patch.object(
            repair_github_watcher_corruption,
            "GitHubWatcherCorruptionRepairService",
            return_value=service,
        ),
        patch.object(repair_github_watcher_corruption.postgres_database, "close"),
    ):
        code = repair_github_watcher_corruption.main(
            ["--target-database", "catalog_test", "--target-schema", "public"]
        )

    output = capsys.readouterr()
    assert code == 1
    assert "RuntimeError" in output.err
    assert "super-secret" not in output.err
