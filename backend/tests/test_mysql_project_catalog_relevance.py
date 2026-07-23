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


def test_lexical_candidates_are_canonical_bounded_and_parameterized() -> None:
    repository, cursor, connection = _repository_with_cursor()
    cursor.fetchall.return_value = [{"repo_id": "owner/repo"}]

    result = repository.find_lexical_candidate_repo_ids(
        q="agent 100%_safe",
        category="agents_automation",
        limit=1000,
    )

    sql, params = cursor.execute.call_args.args
    assert result == ["owner/repo"]
    assert "github_repo_aliases ga" in sql
    assert "ga.alias_repo_id IS NULL" in sql
    assert "LIMIT %s" in sql
    assert params[-1] == 200
    assert "100%_safe" not in sql
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_empty_lexical_query_does_not_connect() -> None:
    repository, _, _ = _repository_with_cursor()

    assert repository.find_lexical_candidate_repo_ids(q="GitHub repository 项目 仓库") == []
    repository._connect.assert_not_called()


def test_relevance_hydration_uses_ordered_candidate_parameters() -> None:
    repository, cursor, connection = _repository_with_cursor()
    cursor.fetchone.return_value = {"cnt": 2}
    cursor.fetchall.return_value = []

    repository.list_projects(
        source="github",
        candidate_repo_ids=["owner/beta", "owner/alpha", "owner/beta"],
        sort="relevance",
        min_stars=0,
    )

    count_call, rows_call = cursor.execute.call_args_list
    count_sql, count_params = count_call.args
    rows_sql, rows_params = rows_call.args
    assert "FIELD(repo_id" not in count_sql
    assert "FIELD(repo_id, %s, %s)" in rows_sql
    assert count_params[-2:] == ("owner/beta", "owner/alpha")
    assert rows_params[-4:] == ("owner/beta", "owner/alpha", 24, 0)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()
