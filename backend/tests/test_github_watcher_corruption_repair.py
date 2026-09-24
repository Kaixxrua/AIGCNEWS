from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
from unittest.mock import MagicMock, patch

import pytest

from backend.app.services.github_watcher_corruption_repair import (
    GitHubWatcherCorruptionRepairService,
    GitHubWatcherRepairSafetyError,
)


class TransactionalDatabase:
    def __init__(self, connection: MagicMock) -> None:
        self.connection = connection

    @contextmanager
    def transaction(self) -> Iterator[MagicMock]:
        yield self.connection


def _service(
    connection: MagicMock,
    *,
    env: str = "development",
    repair_authorized: bool = False,
) -> GitHubWatcherCorruptionRepairService:
    return GitHubWatcherCorruptionRepairService(
        postgres=TransactionalDatabase(connection),  # type: ignore[arg-type]
        config=type(
            "Config",
            (),
            {
                "env": env,
                "github_watcher_repair_production_authorized": repair_authorized,
            },
        )(),
    )


def _target() -> dict[str, object]:
    return {"database": "catalog_test", "schema": "public", "schema_version": 10}


def test_dry_run_inspects_without_locking_or_mutating() -> None:
    connection = MagicMock()
    service = _service(connection)
    row = {
        "id": 1,
        "repo_id": "acme/repo",
        "snapshot_date": "2026-07-28",
        "stars": 700,
        "watchers": 700,
    }
    with (
        patch.object(service, "_inspect_target", return_value=_target()),
        patch.object(service, "_find_corrupted_snapshots", return_value=[row]),
        patch.object(service, "_has_corrupted_snapshots_after", return_value=False),
        patch.object(service, "_apply_batch") as apply_batch,
    ):
        result = service.repair(
            target_database="catalog_test",
            target_schema="public",
        )

    assert result["applied"] is False
    assert result["matched"] == 1
    assert result["samples"] == [
        {
            "repo_id": "acme/repo",
            "snapshot_date": "2026-07-28",
            "stars": 700,
            "watchers": 700,
        }
    ]
    apply_batch.assert_not_called()


def test_apply_repairs_selected_batch_and_reports_cursor() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"acquired": True}
    service = _service(connection)
    rows = [
        {
            "id": index,
            "repo_id": f"acme/repo-{index}",
            "snapshot_date": "2026-07-28",
            "stars": 700 + index,
            "watchers": 700 + index,
        }
        for index in range(1, 4)
    ]
    with (
        patch.object(service, "_inspect_target", return_value=_target()),
        patch.object(service, "_find_corrupted_snapshots", return_value=rows[:2]),
        patch.object(service, "_has_corrupted_snapshots_after", return_value=True),
        patch.object(
            service,
            "_apply_batch",
            return_value={
                "snapshots_quarantined": 2,
                "candidates_cleared": 2,
                "daily_watchers_cleared": 2,
                "daily_metrics_rebuilt": 4,
            },
        ) as apply_batch,
    ):
        result = service.repair(
            target_database="catalog_test",
            target_schema="public",
            batch_size=2,
            apply=True,
        )

    assert result["applied"] is True
    assert result["matched"] == 2
    assert result["has_more"] is True
    assert result["next_cursor"] == {
        "snapshot_date": "2026-07-28",
        "repo_id": "acme/repo-2",
    }
    apply_batch.assert_called_once_with(connection, rows[:2])


def test_apply_batch_quarantines_snapshots_and_rebuilds_only_community_contribution() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.rowcount = 1
    rows = [
        {
            "id": 1,
            "repo_id": "acme/repo",
            "snapshot_date": "2026-07-28",
            "stars": 700,
            "watchers": 700,
        }
    ]

    result = _service(connection)._apply_batch(connection, rows)

    calls = cursor.execute.call_args_list
    assert "community_metrics_complete=FALSE" in calls[0].args[0]
    assert "WITH latest_complete AS" in calls[1].args[0]
    assert "COALESCE(latest_complete.watchers,0)" in calls[1].args[0]
    assert "SET watchers=0" in calls[2].args[0]
    rebuild_sql = calls[3].args[0]
    assert "daily_fork_growth=0" in rebuild_sql
    assert "daily_watcher_growth=0" in rebuild_sql
    assert "community_engagement_score=0.0" in rebuild_sql
    assert "0.55*scale_corrected_growth_score" in rebuild_sql
    assert "score_version='daily_hot_v6'" in rebuild_sql
    assert "score_version='daily_hot_v7'" in rebuild_sql
    assert calls[3].args[1] == (
        ["acme/repo", "acme/repo"],
        ["2026-07-28", "2026-07-29"],
    )
    assert result == {
        "snapshots_quarantined": 1,
        "candidates_cleared": 1,
        "daily_watchers_cleared": 1,
        "daily_metrics_rebuilt": 1,
    }


def test_apply_fails_when_corruption_reappears_behind_cursor() -> None:
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"acquired": True}
    service = _service(connection)
    stale = {
        "id": 1,
        "repo_id": "acme/stale",
        "snapshot_date": "2026-07-20",
        "stars": 700,
        "watchers": 700,
    }
    with (
        patch.object(service, "_inspect_target", return_value=_target()),
        patch.object(service, "_find_corrupted_snapshots", side_effect=[[], [stale]]),
        patch.object(service, "_has_corrupted_snapshots_after", return_value=False),
    ):
        with pytest.raises(
            GitHubWatcherRepairSafetyError,
            match="behind the repair cursor",
        ):
            service.repair(
                target_database="catalog_test",
                target_schema="public",
                after_snapshot_date="2026-07-28",
                after_repo_id="acme/repo",
                apply=True,
            )


def test_batch_size_and_cursor_are_bounded() -> None:
    service = _service(MagicMock())
    for value in (0, 1001):
        with pytest.raises(GitHubWatcherRepairSafetyError):
            service.repair(
                target_database="catalog_test",
                target_schema="public",
                batch_size=value,
            )
    with pytest.raises(GitHubWatcherRepairSafetyError):
        service.repair(
            target_database="catalog_test",
            target_schema="public",
            after_snapshot_date="2026-07-28",
        )


def test_production_apply_requires_two_independent_authorizations() -> None:
    # CLI 已授权但环境第二通道未授权 → 拒绝
    service = _service(MagicMock(), env="production", repair_authorized=False)
    with pytest.raises(GitHubWatcherRepairSafetyError):
        service.repair(
            target_database="catalog_test",
            target_schema="public",
            apply=True,
            production_authorized=True,
        )
    # 环境第二通道已授权但 CLI 未授权 → 拒绝
    service = _service(MagicMock(), env="production", repair_authorized=True)
    with pytest.raises(GitHubWatcherRepairSafetyError):
        service.repair(
            target_database="catalog_test",
            target_schema="public",
            apply=True,
            production_authorized=False,
        )
