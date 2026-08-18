from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from backend.app.repositories.postgres_project_ingestion_repository import (
    PostgresGitHubProjectIngestionRepository,
)


class FakeDatabase:
    def __init__(self, cursor: MagicMock) -> None:
        self.cursor = cursor
        self.connection = MagicMock()
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        self.connection.cursor.return_value = cursor_context
        self.transaction_count = 0

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        yield self.connection


def repository_with_cursor():
    cursor = MagicMock()
    # _resolve_repo_id 的两次 SELECT 均无命中 → canonical 回退为 full_name/repo_id
    cursor.fetchone.return_value = None
    database = FakeDatabase(cursor)
    return PostgresGitHubProjectIngestionRepository(database), database, cursor


def _observation(repo_id: str, full_name: str, **snapshot_overrides) -> dict:
    snapshot = {
        "repo_id": repo_id,
        "full_name": full_name,
        "snapshot_date": "2026-07-30",
        "captured_at": "2026-07-30T01:00:00+00:00",
        "stars": 100,
        "community_metrics_complete": 1,
    }
    snapshot.update(snapshot_overrides)
    return {
        "candidate": {
            "repo_id": repo_id,
            "full_name": full_name,
            "stars": 100,
            "community_metrics_complete": True,
            "source_channels": "daily_metrics",
            "last_snapshot_at": "2026-07-30T01:00:00+00:00",
        },
        "available_full_name": full_name,
        "snapshot": snapshot,
    }


def test_upsert_metric_observations_uses_single_transaction_and_executemany() -> None:
    repository, database, cursor = repository_with_cursor()

    written = repository.upsert_github_repo_metric_observations(
        [
            _observation("owner/one", "owner/one"),
            _observation("owner/two", "owner/two"),
        ],
        checked_at="2026-07-30T01:00:00+00:00",
    )

    assert written == 2
    assert database.transaction_count == 1
    assert cursor.executemany.call_count == 3

    candidate_sql, candidate_params = cursor.executemany.call_args_list[0].args
    assert "INSERT INTO github_repo_candidates" in candidate_sql
    assert [row["repo_id"] for row in candidate_params] == ["owner/one", "owner/two"]
    assert all(row["community_metrics_complete"] is True for row in candidate_params)

    mark_sql, mark_params = cursor.executemany.call_args_list[1].args
    assert "availability_status='active'" in mark_sql
    assert mark_params == [
        ("2026-07-30T01:00:00+00:00", "owner/one"),
        ("2026-07-30T01:00:00+00:00", "owner/two"),
    ]

    snapshot_sql, snapshot_params = cursor.executemany.call_args_list[2].args
    assert "INSERT INTO github_repo_snapshots" in snapshot_sql
    assert [row["repo_id"] for row in snapshot_params] == ["owner/one", "owner/two"]
    # 快照归一化与单行方法一致：completeness 转 bool、缺省列补默认值
    assert all(row["community_metrics_complete"] is True for row in snapshot_params)
    assert all(row["open_issues"] == 0 for row in snapshot_params)
    assert all(row["repo_created_at"] == "" for row in snapshot_params)
    assert all(row["repo_pushed_at"] == "" for row in snapshot_params)


def test_upsert_metric_observations_empty_batch_opens_no_transaction() -> None:
    repository, database, cursor = repository_with_cursor()

    assert repository.upsert_github_repo_metric_observations([], checked_at="now") == 0
    assert database.transaction_count == 0
    cursor.executemany.assert_not_called()


def test_upsert_metric_observations_failure_propagates_out_of_one_transaction() -> None:
    repository, database, cursor = repository_with_cursor()
    cursor.executemany.side_effect = [None, None, RuntimeError("insert failed")]

    with pytest.raises(RuntimeError, match="insert failed"):
        repository.upsert_github_repo_metric_observations(
            [_observation("owner/one", "owner/one")],
            checked_at="2026-07-30T01:00:00+00:00",
        )

    # 只开启了一个事务：候选 upsert 与可用性恢复随失败一起回滚，不留中间态
    assert database.transaction_count == 1


def test_candidate_upsert_sql_carries_license_spdx_id() -> None:
    repository, _, cursor = repository_with_cursor()
    observation = _observation("owner/one", "owner/one")
    observation["candidate"]["license_spdx_id"] = "Apache-2.0"

    repository.upsert_github_repo_metric_observations([observation], checked_at="now")

    candidate_sql, candidate_params = cursor.executemany.call_args_list[0].args
    assert "license_spdx_id" in candidate_sql
    assert [row["license_spdx_id"] for row in candidate_params] == ["Apache-2.0"]


def test_candidate_payload_defaults_license_spdx_id_empty() -> None:
    payload = PostgresGitHubProjectIngestionRepository._candidate_payload(
        {"repo_id": "owner/one", "full_name": "owner/one"}
    )

    assert payload["license_spdx_id"] == ""

