from __future__ import annotations

from unittest.mock import MagicMock

from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.repositories.project_catalog import (
    ProjectLexicalCandidate,
    ProjectLexicalConcept,
    ProjectLexicalRetrievalPlan,
)


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
    assert not repository.find_lexical_candidate_lanes(q="GitHub repository 项目 仓库").strict
    repository._connect.assert_not_called()


def test_lexical_lanes_are_typed_filtered_and_independently_bounded() -> None:
    repository, cursor, connection = _repository_with_cursor()
    cursor.fetchall.side_effect = [
        [{"repo_id": "owner/strict", "term_coverage": 2, "match_strength": 4}],
        [{"repo_id": "owner/relaxed", "term_coverage": 1, "match_strength": 1}],
    ]

    result = repository.find_lexical_candidate_lanes(
        q="agent 100%_safe",
        category="agents_automation",
        subcategory="agent_framework",
        language="Python",
        tag="MCP",
        strict_limit=1000,
        relaxed_limit=999,
    )

    assert result.strict == (
        ProjectLexicalCandidate("owner/strict", "strict", term_coverage=2, match_strength=4),
    )
    assert result.relaxed == (
        ProjectLexicalCandidate("owner/relaxed", "relaxed", term_coverage=1, match_strength=1),
    )
    strict_call, relaxed_call = cursor.execute.call_args_list
    strict_sql, strict_params = strict_call.args
    relaxed_sql, relaxed_params = relaxed_call.args
    for sql in (strict_sql, relaxed_sql):
        assert "github_repo_aliases ga" in sql
        assert "ga.alias_repo_id IS NULL" in sql
        assert "COALESCE(c.stars, 0) >= %s" in sql
        assert "ge.category_slug = %s" in sql
        assert "ge.subcategory_slug = %s" in sql
        assert "LOWER(COALESCE(c.language, '')) = LOWER(%s)" in sql
        assert "COALESCE(ge.tags_json, '') LIKE %s" in sql
        assert "100%_safe" not in sql
    assert "term_coverage = %s" in strict_sql
    assert "term_coverage > 0" in relaxed_sql
    assert strict_params[-2:] == (3, 150)
    assert relaxed_params[-1] == 150
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


def test_typed_lexical_plan_requires_terms_and_concepts_independently() -> None:
    repository, cursor, connection = _repository_with_cursor()
    cursor.fetchall.side_effect = [[], []]
    plan = ProjectLexicalRetrievalPlan(
        normalized_query="Python MCP agent",
        strict_terms=("Python",),
        concepts=(
            ProjectLexicalConcept(
                concept_id="mcp",
                primary_terms=("MCP",),
                aliases=("model context protocol", "100%_safe"),
            ),
            ProjectLexicalConcept(
                concept_id="agent",
                primary_terms=("agent",),
                aliases=("智能体",),
            ),
        ),
    )

    repository.find_lexical_candidate_lanes(q=plan)

    strict_call, relaxed_call = cursor.execute.call_args_list
    strict_sql, strict_params = strict_call.args
    relaxed_sql, relaxed_params = relaxed_call.args
    assert "term_coverage = %s" in strict_sql
    assert strict_params[-2:] == (3, 150)
    assert relaxed_params[-1] == 150
    assert "100%_safe" not in strict_sql
    assert "%100=%=_safe%" in strict_params
    assert strict_params.count("%MCP%") == 7
    assert strict_params.count("%model context protocol%") == 7
    assert strict_params.count("%100=%=_safe%") == 7
    assert strict_params == relaxed_params[:-1] + (3, 150)
    connection.commit.assert_called_once_with()
    connection.close.assert_called_once_with()


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
