from __future__ import annotations

import inspect
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from backend.app.repositories.project_catalog import (
    ProjectCatalogRepository,
    ProjectLexicalCandidate,
)
from backend.app.repositories.project_catalog_normalization import (
    format_project_category_counts,
    normalize_project_row,
)
from backend.app.repositories.postgres_project_catalog import PostgresProjectCatalogRepository


class Cursor:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, Any]] = []

    def __enter__(self) -> Cursor:
        return self

    def __exit__(self, *args: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.calls.append((sql, params))

    def fetchone(self) -> Any:
        return self.responses.pop(0)

    def fetchall(self) -> Any:
        return self.responses.pop(0)


class Database:
    def __init__(self, responses: list[Any]) -> None:
        self.cursor = Cursor(responses)
        self.connection = MagicMock()
        self.connection.cursor.return_value = self.cursor
        self.entered = 0
        self.exited = 0

    @contextmanager
    def transaction(self):
        self.entered += 1
        try:
            yield self.connection
        finally:
            self.exited += 1


def stripped(function: Any) -> inspect.Signature:
    signature = inspect.signature(function)
    return signature.replace(
        parameters=[item.replace(annotation=inspect.Parameter.empty) for item in signature.parameters.values()],
        return_annotation=inspect.Signature.empty,
    )


def test_signatures_match_frozen_contract_exactly() -> None:
    assert stripped(PostgresProjectCatalogRepository.find_lexical_candidate_repo_ids) == stripped(ProjectCatalogRepository.find_lexical_candidate_repo_ids)
    assert stripped(PostgresProjectCatalogRepository.find_lexical_candidate_lanes) == stripped(ProjectCatalogRepository.find_lexical_candidate_lanes)
    assert stripped(PostgresProjectCatalogRepository.list_projects) == stripped(ProjectCatalogRepository.list_projects)
    assert stripped(PostgresProjectCatalogRepository.get_project_categories) == stripped(ProjectCatalogRepository.get_project_categories)


def test_empty_candidate_list_short_circuits_without_transaction() -> None:
    database = Database([])
    result = PostgresProjectCatalogRepository(database).list_projects(candidate_repo_ids=[])
    assert result == {"items": [], "total": 0, "page": 1, "page_size": 24}
    assert database.entered == 0


def test_candidate_ids_and_injection_values_are_bound_not_interpolated() -> None:
    attack = "owner/repo') OR TRUE --"
    database = Database([{"cnt": 0}, []])
    result = PostgresProjectCatalogRepository(database).list_projects(
        candidate_repo_ids=[attack, attack, "exact/canonical"], q="100%_safe", tag='x" OR TRUE --'
    )
    assert result["total"] == 0
    assert database.entered == database.exited == 1
    calls = database.cursor.calls
    assert calls[0] == ("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY", None)
    count_sql, params = calls[1]
    assert "c.repo_id = ANY(%s)" in count_sql
    assert attack not in count_sql
    assert [attack, "exact/canonical"] in params
    assert 'x" OR TRUE --' not in count_sql
    assert any(value == "%100%" for value in params)
    assert any(value == "%safe%" for value in params)
    assert all("github_repo_aliases" not in sql for sql, _ in calls)


def test_lexical_candidates_are_canonical_bounded_and_parameterized() -> None:
    database = Database([[{"repo_id": "owner/repo"}]])
    result = PostgresProjectCatalogRepository(database).find_lexical_candidate_repo_ids(
        q="agent 100%_safe",
        category="agents_automation",
        limit=1000,
    )
    assert result == ["owner/repo"]
    sql, params = database.cursor.calls[1]
    assert "github_repo_aliases ga" in sql
    assert "ga.alias_repo_id IS NULL" in sql
    assert "LIMIT %s" in sql
    assert params[-1] == 200
    assert "100%_safe" not in sql


def test_empty_lexical_lanes_short_circuit_without_transaction() -> None:
    database = Database([])
    result = PostgresProjectCatalogRepository(database).find_lexical_candidate_lanes(
        q="GitHub repository 项目 仓库"
    )

    assert not result.strict
    assert not result.relaxed
    assert database.entered == 0


def test_lexical_lanes_are_typed_filtered_and_independently_bounded() -> None:
    database = Database([
        [{"repo_id": "owner/strict", "term_coverage": 3, "match_strength": 4}],
        [{"repo_id": "owner/relaxed", "term_coverage": 1, "match_strength": 1}],
    ])
    result = PostgresProjectCatalogRepository(database).find_lexical_candidate_lanes(
        q="agent 100%_safe",
        category="agents_automation",
        subcategory="agent_framework",
        language="Python",
        tag="MCP",
        strict_limit=1000,
        relaxed_limit=999,
    )

    assert result.strict == (
        ProjectLexicalCandidate("owner/strict", "strict", term_coverage=3, match_strength=4),
    )
    assert result.relaxed == (
        ProjectLexicalCandidate("owner/relaxed", "relaxed", term_coverage=1, match_strength=1),
    )
    strict_sql, strict_params = database.cursor.calls[1]
    relaxed_sql, relaxed_params = database.cursor.calls[2]
    for sql in (strict_sql, relaxed_sql):
        assert "github_repo_aliases ga" in sql
        assert "ga.alias_repo_id IS NULL" in sql
        assert "COALESCE(c.stars, 0) >= %s" in sql
        assert "ge.category_slug = %s" in sql
        assert "ge.subcategory_slug = %s" in sql
        assert "LOWER(COALESCE(c.language, '')) = LOWER(%s)" in sql
        assert "COALESCE(ge.tags_json::text, '') ILIKE %s" in sql
        assert "unnest(%s::text[])" in sql
        assert "100%_safe" not in sql
    assert "term_coverage = %s" in strict_sql
    assert "term_coverage > 0" in relaxed_sql
    assert strict_params[-2:] == (3, 150)
    assert relaxed_params[-1] == 150
    assert ["%agent%", "%100%", "%safe%"] in strict_params
    assert database.entered == database.exited == 1


def test_relevance_hydration_preserves_candidate_order_parameters() -> None:
    database = Database([{"cnt": 2}, []])
    candidates = ["owner/beta", "owner/alpha", "owner/beta"]
    PostgresProjectCatalogRepository(database).list_projects(
        candidate_repo_ids=candidates,
        sort="relevance",
        min_stars=0,
    )
    count_sql, count_params = database.cursor.calls[1]
    rows_sql, rows_params = database.cursor.calls[2]
    assert "array_position(%s::text[],repo_id)" not in count_sql
    assert "array_position(%s::text[],repo_id)" in rows_sql
    assert ["owner/beta", "owner/alpha"] in count_params
    assert rows_params[-3:] == (["owner/beta", "owner/alpha"], 24, 0)


def test_representative_website_user_overrides_and_favorites_branch() -> None:
    database = Database([{"cnt": 0}, []])
    PostgresProjectCatalogRepository(database).list_projects(
        source="website", user_id=7, favorites_only=True, enriched_only=True,
        category="other", subcategory="other_uncategorized", language="Python",
    )
    sql, params = database.cursor.calls[1]
    assert "user_tool_website_overrides uo" in sql
    assert "we.status = 'succeeded' OR uo.id IS NOT NULL OR utw.id IS NOT NULL" in sql
    assert "pf.id IS NOT NULL OR utw.id IS NOT NULL" in sql
    assert "uo.tags_json::text" in sql
    assert "w.visibility = 'public'" not in sql
    assert "FALSE" in sql  # websites cannot satisfy language filtering
    assert params.count(7) == 3


def test_tag_filters_are_case_insensitive_like_mysql() -> None:
    lexical_database = Database([[]])
    PostgresProjectCatalogRepository(lexical_database).find_lexical_candidate_repo_ids(
        q="agent", tag="mcp"
    )
    assert "COALESCE(ge.tags_json::text, '') ILIKE %s" in lexical_database.cursor.calls[1][0]

    database = Database([{"cnt": 0}, []])
    PostgresProjectCatalogRepository(database).list_projects(tag="mcp")
    sql = database.cursor.calls[1][0]
    assert "COALESCE(ge.tags_json::text, '') ILIKE %s" in sql
    assert "COALESCE(we.tags_json::text, '') ILIKE %s" in sql


def test_recent_sort_ignores_empty_legacy_timestamps_before_casting() -> None:
    database = Database([{"cnt": 0}, []])
    PostgresProjectCatalogRepository(database).list_projects(sort="recent")
    rows_sql = database.cursor.calls[2][0]
    assert "NULLIF(first_seen_at,'')::timestamptz" in rows_sql
    assert "NULLIF(last_seen_at,'')::timestamptz" in rows_sql


def test_today_branch_forces_hot_order_and_uses_bounded_top_set() -> None:
    database = Database([{"cnt": 0}, []])
    PostgresProjectCatalogRepository(database).list_projects(scope="today", sort="name")
    rows_sql = database.cursor.calls[2][0]
    assert "LIMIT 50" in rows_sql
    assert "ORDER BY hot_score DESC NULLS LAST,daily_star_growth DESC NULLS LAST" in rows_sql


def test_categories_use_one_consistent_read_transaction_and_three_queries() -> None:
    database = Database([[{"category_slug": "other", "category_name": "Other", "subcategory_slug": "", "subcategory_name": "", "count": 2}], {"count": 1}, {"count": 1}])
    result = PostgresProjectCatalogRepository(database).get_project_categories(user_id=4, favorites_only=True)
    assert database.entered == database.exited == 1
    assert len(database.cursor.calls) == 4
    assert database.cursor.calls[0][0].startswith("SET TRANSACTION")
    assert result["total"] == 2
    assert result["today_count"] == 1
    assert result["recommended_count"] == 1
    other = next(item for item in result["items"] if item["slug"] == "other")
    assert other["children"][0]["count"] == 2


def test_transaction_is_closed_when_query_raises() -> None:
    database = Database([])
    database.cursor.execute = MagicMock(side_effect=RuntimeError("database unavailable"))
    with pytest.raises(RuntimeError, match="database unavailable"):
        PostgresProjectCatalogRepository(database).list_projects()
    assert database.entered == database.exited == 1


def test_normalization_matches_mysql_shape_and_json_text_semantics() -> None:
    row = {
        "source": "website", "tags_json": '["AI", "  docs ", ""]', "topics_json": '["web"]',
        "stars": None, "daily_growth_available": True, "rank_in_period": 0,
        "confidence": "0.5", "is_favorited": 1, "is_recommended": 0, "user_added": 1,
        "favorited_at": datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc),
        "category_slug": "", "subcategory_slug": "",
    }
    item = normalize_project_row(row)
    assert item["tags"] == ["AI", "docs"]
    assert item["topics"] == ["web"]
    assert "tags_json" not in item and "topics_json" not in item
    assert item["stars"] == 0 and item["rank_in_period"] is None
    assert item["confidence"] == 0.5 and item["is_favorited"] is True
    assert item["favorited_at"] == "2026-01-02T03:04:00Z"
    assert item["category_slug"] == "other"
    assert item["subcategory_slug"] == "other_uncategorized"
    assert item["category_name"] == "其他网站"


def test_dynamic_category_formatting_preserves_taxonomy_and_defaults() -> None:
    result = format_project_category_counts([
        {"category_slug": "custom", "category_name": "Custom", "subcategory_slug": "x", "subcategory_name": "X", "count": 3},
        {"category_slug": "other", "category_name": "", "subcategory_slug": "", "subcategory_name": "", "count": 2},
    ])
    assert result["total"] == 5
    assert result["items"][-1] == {"slug": "custom", "name": "Custom", "count": 3, "kind": "category", "children": [{"slug": "x", "name": "X", "count": 3}]}
