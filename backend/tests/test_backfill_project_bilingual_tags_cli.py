from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from scripts import backfill_project_bilingual_tags as cli


def test_cli_forwards_cursors_and_dry_run(capsys) -> None:
    github = MagicMock()
    github.backfill_bilingual_tags.return_value = {
        "status": "dry_run", "processed": 2, "next_cursor": "20",
    }
    website = MagicMock()
    website.backfill_bilingual_tags.return_value = {
        "status": "dry_run", "processed": 1, "next_cursor": 9,
    }
    with patch.object(cli, "GitHubProjectEnricher", return_value=github), patch.object(
        cli, "ToolWebsiteEnricher", return_value=website,
    ):
        code = cli.main([
            "--source", "all", "--after-repo-id", "10",
            "--after-website-id", "4", "--limit", "25",
            "--min-stars", "700", "--dry-run",
        ])

    assert code == 0
    github.backfill_bilingual_tags.assert_called_once_with(
        after_repo_id="10", limit=25, min_stars=700, dry_run=True,
    )
    website.backfill_bilingual_tags.assert_called_once_with(
        after_website_id=4, limit=25, dry_run=True,
    )
    assert json.loads(capsys.readouterr().out)["status"] == "dry_run"


def test_cli_returns_failure_for_partial_backfill(capsys) -> None:
    github = MagicMock()
    github.backfill_bilingual_tags.return_value = {"status": "partial"}
    with patch.object(cli, "GitHubProjectEnricher", return_value=github):
        code = cli.main(["--source", "github"])

    assert code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "partial"
