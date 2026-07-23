from __future__ import annotations

from unittest.mock import MagicMock

from backend.app.repositories.mysql_repo import MySQLRepository


def _repository_with_cursor() -> tuple[MySQLRepository, MagicMock, MagicMock]:
    cursor = MagicMock()
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    repository = object.__new__(MySQLRepository)
    repository._connect = MagicMock(return_value=connection)
    return repository, cursor, connection


def test_semantic_sync_excludes_noncanonical_alias_candidates() -> None:
    repository, cursor, connection = _repository_with_cursor()
    cursor.fetchall.return_value = [
        {
            "repo_id": "owner/canonical",
            "full_name": "owner/canonical",
            "topics_json": '["frontend"]',
            "tags_json": '["developer-tools"]',
            "stars": 1000,
            "forks": 10,
        }
    ]

    projects = repository.list_github_projects_for_semantic_sync(
        limit=100,
        min_stars=500,
        after_repo_id="owner/alpha",
    )

    sql, params = cursor.execute.call_args.args
    assert "github_repo_aliases" in sql
    assert "alias_repo_id = c.repo_id" in sql
    assert "canonical_repo_id <> c.repo_id" in sql
    assert projects[0]["repo_id"] == "owner/canonical"
    assert projects[0]["topics"] == ["frontend"]
    assert projects[0]["tags"] == ["developer-tools"]
    assert params == (500, "owner/alpha", "pending", "failed", "v1", 100)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_semantic_status_uses_same_canonical_eligibility_rule() -> None:
    repository, cursor, connection = _repository_with_cursor()
    cursor.fetchone.return_value = {
        "eligible": 10,
        "indexed": 8,
        "failed": 1,
        "readme_succeeded": 4,
        "chunk_count": 20,
        "last_indexed_at": "2026-07-23T12:00:00+00:00",
    }

    status = repository.get_github_project_semantic_status(min_stars=500)

    sql, params = cursor.execute.call_args.args
    assert "github_repo_aliases" in sql
    assert "alias_repo_id = c.repo_id" in sql
    assert "canonical_repo_id <> c.repo_id" in sql
    assert params == (500,)
    assert status["pending"] == 1
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()
