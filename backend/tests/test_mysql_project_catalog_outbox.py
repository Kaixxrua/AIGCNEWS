from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from backend.app.repositories import mysql_repo
from backend.app.repositories.mysql_repo import MySQLRepository


def _repository_with_connection() -> tuple[MySQLRepository, MagicMock, MagicMock]:
    repository = object.__new__(MySQLRepository)
    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    repository._connect = MagicMock(return_value=connection)
    return repository, connection, cursor


def test_capture_disabled_emits_no_sql() -> None:
    cursor = MagicMock()
    with patch.object(
        mysql_repo.settings,
        "project_catalog_outbox_capture_enabled",
        False,
    ):
        MySQLRepository._record_project_catalog_change_cur(
            cursor,
            aggregate_type="github_repo_candidates",
            aggregate_key={"repo_id": "repo-1"},
            source_method="test",
        )
    cursor.execute.assert_not_called()


def test_capture_enabled_emits_only_canonical_key_coordinates() -> None:
    cursor = MagicMock()
    with patch.object(
        mysql_repo.settings,
        "project_catalog_outbox_capture_enabled",
        True,
    ):
        MySQLRepository._record_project_catalog_change_cur(
            cursor,
            aggregate_type="project_favorites",
            aggregate_key={"项目": "工具", "user_id": 7},
            operation="delete",
            source_method="test_capture",
        )

    sql, params = cursor.execute.call_args.args
    assert "INSERT INTO project_catalog_outbox" in sql
    uuid.UUID(params[0])
    assert params[1:] == (
        "project_favorites",
        '{"user_id":7,"项目":"工具"}',
        "delete",
        "test_capture",
    )
    decoded = json.loads(params[2])
    assert decoded == {"user_id": 7, "项目": "工具"}
    assert "description" not in params[2]
    assert "readme" not in params[2].lower()


def test_candidate_and_outbox_share_one_commit() -> None:
    repository, connection, cursor = _repository_with_connection()
    repository._resolve_github_repo_id_cur = MagicMock(return_value="canonical-1")
    repository._upsert_github_repo_alias_cur = MagicMock()

    with patch.object(
        mysql_repo.settings,
        "project_catalog_outbox_capture_enabled",
        True,
    ):
        result = repository.ensure_github_repo_candidate(
            {"repo_id": "requested-1", "full_name": "owner/repo"}
        )

    assert result == "canonical-1"
    assert cursor.execute.call_count == 2
    assert "INSERT IGNORE INTO github_repo_candidates" in cursor.execute.call_args_list[0].args[0]
    assert "INSERT INTO project_catalog_outbox" in cursor.execute.call_args_list[1].args[0]
    assert json.loads(cursor.execute.call_args_list[1].args[1][2]) == {
        "repo_id": "canonical-1"
    }
    connection.commit.assert_called_once_with()
    connection.rollback.assert_not_called()
    connection.close.assert_called_once_with()


def test_outbox_failure_rolls_back_candidate_write() -> None:
    repository, connection, cursor = _repository_with_connection()
    repository._resolve_github_repo_id_cur = MagicMock(return_value="canonical-1")
    repository._upsert_github_repo_alias_cur = MagicMock()
    failure = RuntimeError("outbox unavailable")
    cursor.execute.side_effect = [None, failure]

    with (
        patch.object(
            mysql_repo.settings,
            "project_catalog_outbox_capture_enabled",
            True,
        ),
        pytest.raises(RuntimeError, match="outbox unavailable"),
    ):
        repository.ensure_github_repo_candidate(
            {"repo_id": "requested-1", "full_name": "owner/repo"}
        )

    connection.commit.assert_not_called()
    connection.rollback.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_website_delete_captures_children_before_parent() -> None:
    repository, connection, cursor = _repository_with_connection()
    cursor.fetchall.side_effect = [
        [{"user_id": 7, "project_source": "website", "project_id": "42"}],
        [{"user_id": 7, "website_id": 42}],
        [{"user_id": 7, "website_id": 42}],
    ]
    cursor.fetchone.return_value = {"website_id": 42}
    cursor.rowcount = 1

    with patch.object(
        mysql_repo.settings,
        "project_catalog_outbox_capture_enabled",
        True,
    ):
        deleted = repository.delete_tool_website(42)

    assert deleted is True
    outbox_calls = [
        call
        for call in cursor.execute.call_args_list
        if "INSERT INTO project_catalog_outbox" in call.args[0]
    ]
    assert [call.args[1][1] for call in outbox_calls] == [
        "project_favorites",
        "user_tool_website_overrides",
        "user_tool_websites",
        "tool_website_enrichments",
        "tool_websites",
    ]
    assert all(call.args[1][3] == "delete" for call in outbox_calls)
    assert json.loads(outbox_calls[-1].args[1][2]) == {"id": 42}
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_daily_metric_capture_preserves_executemany_rowcount() -> None:
    repository, connection, cursor = _repository_with_connection()
    cursor.rowcount = 2
    metrics = [
        {"repo_id": "repo-1", "metric_date": "2026-07-22"},
        {"repo_id": "repo-2", "metric_date": "2026-07-23"},
    ]

    with patch.object(
        mysql_repo.settings,
        "project_catalog_outbox_capture_enabled",
        True,
    ):
        affected = repository.upsert_github_daily_metrics(metrics)

    assert affected == 2
    cursor.executemany.assert_called_once()
    assert cursor.execute.call_count == 2
    keys = [json.loads(call.args[1][2]) for call in cursor.execute.call_args_list]
    assert keys == [
        {"metric_date": "2026-07-22", "repo_id": "repo-1"},
        {"metric_date": "2026-07-23", "repo_id": "repo-2"},
    ]
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_daily_metric_outbox_failure_prevents_transaction_commit() -> None:
    repository, connection, cursor = _repository_with_connection()
    cursor.rowcount = 1
    cursor.execute.side_effect = RuntimeError("outbox unavailable")

    with (
        patch.object(
            mysql_repo.settings,
            "project_catalog_outbox_capture_enabled",
            True,
        ),
        pytest.raises(RuntimeError, match="outbox unavailable"),
    ):
        repository.upsert_github_daily_metrics(
            [{"repo_id": "repo-1", "metric_date": "2026-07-22"}]
        )

    cursor.executemany.assert_called_once()
    connection.commit.assert_not_called()
    connection.close.assert_called_once_with()
