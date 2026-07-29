from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.app.repositories import mysql_repo
from backend.app.repositories.mysql_repo import MySQLRepository


def _adapter_with_connection() -> tuple[MySQLRepository, MagicMock, MagicMock]:
    """Keep construction isolated so a dedicated adapter can replace the repository."""
    adapter = object.__new__(MySQLRepository)
    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    adapter._connect = MagicMock(return_value=connection)
    return adapter, connection, cursor


def test_semantic_selection_uses_cursor_order_limit_and_excludes_aliases() -> None:
    adapter, connection, cursor = _adapter_with_connection()
    cursor.fetchall.return_value = []

    assert adapter.list_github_projects_for_semantic_sync(
        limit=25,
        min_stars=700,
        after_repo_id="repo-100",
    ) == []

    sql, params = cursor.execute.call_args.args
    assert "ga.alias_repo_id IS NULL" in sql
    assert "c.repo_id > %s" in sql
    assert "ORDER BY c.repo_id ASC" in sql
    assert "LIMIT %s" in sql
    assert params[0:2] == (700, "repo-100")
    assert params[2:4] == ("pending", "failed")
    assert params[-1] == 25
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_semantic_selection_can_exclude_failed_retries() -> None:
    adapter, _, cursor = _adapter_with_connection()
    cursor.fetchall.return_value = []

    adapter.list_github_projects_for_semantic_sync(retry_failed=False)

    sql, params = cursor.execute.call_args.args
    assert "ss.index_status IN (%s)" in sql
    assert params[2] == "pending"
    assert "failed" not in params


@pytest.mark.parametrize(("requested", "expected"), [(0, 100), (-1, 1), (5000, 1000)])
def test_semantic_selection_clamps_limit(requested: int, expected: int) -> None:
    adapter, _, cursor = _adapter_with_connection()
    cursor.fetchall.return_value = []

    adapter.list_github_projects_for_semantic_sync(limit=requested)

    assert cursor.execute.call_args.args[1][-1] == expected


def test_semantic_source_upsert_resolves_canonical_id_and_captures_same_transaction() -> None:
    adapter, connection, cursor = _adapter_with_connection()
    adapter._resolve_github_repo_id_cur = MagicMock(return_value="canonical-1")

    with patch.object(mysql_repo.settings, "project_catalog_outbox_capture_enabled", True):
        adapter.upsert_github_project_semantic_source(
            {
                "repo_id": "alias-1",
                "source_fingerprint": "source-1",
                "index_status": "succeeded",
            }
        )

    assert cursor.execute.call_count == 2
    write_sql, write_payload = cursor.execute.call_args_list[0].args
    assert "INSERT INTO github_project_semantic_sources" in write_sql
    assert write_payload["repo_id"] == "canonical-1"
    assert write_payload["readme_status"] == "pending"
    assert write_payload["index_retry_count"] == 0
    outbox_sql, outbox_params = cursor.execute.call_args_list[1].args
    assert "INSERT INTO project_catalog_outbox" in outbox_sql
    assert outbox_params[1] == "github_project_semantic_sources"
    assert json.loads(outbox_params[2]) == {"repo_id": "canonical-1"}
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_semantic_source_outbox_failure_prevents_commit() -> None:
    adapter, connection, cursor = _adapter_with_connection()
    adapter._resolve_github_repo_id_cur = MagicMock(return_value="canonical-1")
    cursor.execute.side_effect = [None, RuntimeError("outbox unavailable")]

    with (
        patch.object(mysql_repo.settings, "project_catalog_outbox_capture_enabled", True),
        pytest.raises(RuntimeError, match="outbox unavailable"),
    ):
        adapter.upsert_github_project_semantic_source({"repo_id": "alias-1"})

    connection.commit.assert_not_called()
    connection.close.assert_called_once_with()


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (
            {
                "eligible": 1,
                "indexed": 4,
                "failed": 3,
                "readme_succeeded": None,
                "chunk_count": None,
                "last_indexed_at": None,
            },
            {
                "eligible": 1,
                "indexed": 4,
                "failed": 3,
                "pending": 0,
                "readme_succeeded": 0,
                "chunk_count": 0,
                "last_indexed_at": None,
            },
        ),
        (
            {
                "eligible": None,
                "indexed": None,
                "failed": None,
                "readme_succeeded": None,
                "chunk_count": None,
            },
            {
                "eligible": 0,
                "indexed": 0,
                "failed": 0,
                "pending": 0,
                "readme_succeeded": 0,
                "chunk_count": 0,
                "last_indexed_at": None,
            },
        ),
    ],
)
def test_semantic_status_counts_are_nonnegative(
    row: dict[str, object], expected: dict[str, object]
) -> None:
    adapter, connection, cursor = _adapter_with_connection()
    cursor.fetchone.return_value = row

    assert adapter.get_github_project_semantic_status(min_stars=900) == expected

    sql, params = cursor.execute.call_args.args
    assert "ga.alias_repo_id IS NULL" in sql
    assert params == (900,)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()
