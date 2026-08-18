from __future__ import annotations

import inspect
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from backend.app.repositories.postgres_project_catalog import (
    RELEVANCE_STRONG_MATCH_THRESHOLD,
    PostgresProjectCatalogRepository,
    _strong_match_clause,
    _strong_match_threshold,
)
from backend.app.repositories.project_catalog import (
    ProjectCatalogRepository,
    ProjectLexicalCandidate,
    ProjectLexicalConcept,
    ProjectLexicalRetrievalPlan,
)
from backend.app.repositories.project_catalog_normalization import (
    format_project_category_counts,
    normalize_project_row,
)


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
    assert stripped(PostgresProjectCatalogRepository.list_github_hot_for_date) == stripped(ProjectCatalogRepository.list_github_hot_for_date)
    assert stripped(PostgresProjectCatalogRepository.list_github_hot_dates) == stripped(ProjectCatalogRepository.list_github_hot_dates)


def test_list_github_hot_for_date_is_parameterized_ordered_and_bounded() -> None:
    rows = [
        {
            "repo_id": "owner/repo",
            "full_name": "owner/repo",
            "metric_date": "2026-08-10",
            "hot_score": 96.5,
        }
    ]
    database = Database([rows])
    result = PostgresProjectCatalogRepository(database).list_github_hot_for_date(
        metric_date="2026-08-10' OR TRUE --",
        limit=1000,
    )
    assert result == rows
    assert database.entered == database.exited == 1
    sql, params = database.cursor.calls[1]
    # 指标日过滤 + 与 list_projects(scope="today") 同一收录口径
    assert "gm.metric_date = %s" in sql
    assert "gm.daily_growth_available = TRUE" in sql
    assert "gm.daily_star_growth > 0" in sql
    assert "COALESCE(c.stars, 0) >= %s" in sql
    assert "c.availability_status = 'active'" in sql
    assert "github_repo_enrichments ge" in sql
    assert "ge.status = 'succeeded'" in sql
    # hot_score(v5) 排序与 /projects 今日暴涨一致
    assert "ORDER BY gm.hot_score DESC NULLS LAST" in sql
    assert "gm.daily_star_growth DESC NULLS LAST" in sql
    # 反作弊打标字段随榜透出（不参与排序与过滤）
    assert "gm.growth_suspicion_score" in sql
    assert "gm.growth_suspicion_signals" in sql
    assert "gm.growth_corroborated" in sql
    # 注入串只进参数不进 SQL；limit 收敛到 500 上限
    assert "OR TRUE" not in sql
    assert params == ("2026-08-10' OR TRUE --", 500, 500)


def test_list_github_hot_for_date_without_enrichment_filter_omits_join() -> None:
    database = Database([[]])
    result = PostgresProjectCatalogRepository(database).list_github_hot_for_date(
        metric_date="2026-08-10",
        limit=10,
        min_stars=100,
        enriched_only=False,
    )
    assert result == []
    sql, params = database.cursor.calls[1]
    assert "github_repo_enrichments" not in sql
    assert params == ("2026-08-10", 100, 10)


def test_list_github_hot_dates_returns_descending_strings_bounded() -> None:
    database = Database([[{"metric_date": "2026-08-10"}, {"metric_date": "2026-08-09"}, {"metric_date": None}]])
    result = PostgresProjectCatalogRepository(database).list_github_hot_dates(limit=1000)
    assert result == ["2026-08-10", "2026-08-09"]
    sql, params = database.cursor.calls[1]
    assert "SELECT DISTINCT metric_date" in sql
    assert "ORDER BY metric_date DESC" in sql
    assert params == (365,)


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
    database = Database([[
        {"lane": "strict", "repo_id": "owner/strict", "term_coverage": 3, "match_strength": 4},
        {"lane": "relaxed", "repo_id": "owner/relaxed", "term_coverage": 1, "match_strength": 1},
    ]])
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
    sql, params = database.cursor.calls[1]
    assert "eligible AS MATERIALIZED" in sql
    assert "raw_hits AS MATERIALIZED" in sql
    assert "scored AS MATERIALIZED" in sql
    assert "github_repo_aliases ga" in sql
    assert "NOT EXISTS" in sql
    assert "COALESCE(c.stars, 0) >= %s" in sql
    assert "ge.category_slug = %s" in sql
    assert "ge.subcategory_slug = %s" in sql
    assert "LOWER(COALESCE(c.language, '')) = LOWER(%s)" in sql
    assert "COALESCE(ge.tags_json::text, '') ILIKE %s" in sql
    assert "UNION ALL" in sql
    assert "SELECT DISTINCT repo_id, group_id" in sql
    assert "unnest(" not in sql
    assert "bool_or(" not in sql
    assert "COALESCE(c.full_name, '') || ' '" in sql
    assert "COALESCE(ge.description_zh, '') || ' '" in sql
    assert "100%_safe" not in sql
    assert "term_coverage = %s" in sql
    assert "term_coverage > 0" in sql
    assert sql.count('repo_id COLLATE "C" ASC') == 3
    assert params[-3:] == (3, 150, 150)
    assert "%agent%" in params
    assert "%100%" in params
    assert "%safe%" in params
    assert len(database.cursor.calls) == 2
    assert database.entered == database.exited == 1


def test_typed_lexical_plan_counts_each_concept_once_and_binds_aliases() -> None:
    database = Database([[]])
    plan = ProjectLexicalRetrievalPlan(
        normalized_query="local agent runtime",
        strict_terms=("local",),
        concepts=(
            ProjectLexicalConcept(
                concept_id="agent",
                primary_terms=("智能体",),
                aliases=("agent", "agent framework"),
            ),
        ),
    )

    PostgresProjectCatalogRepository(database).find_lexical_candidate_lanes(q=plan)

    sql, params = database.cursor.calls[1]
    assert "SELECT DISTINCT repo_id, group_id" in sql
    assert params.count("term:0") == 2
    assert params.count("concept:agent") == 6
    for pattern in ("%local%", "%智能体%", "%agent%", "%agent framework%"):
        assert params.count(pattern) == 2
    assert params[-3:] == (2, 150, 150)
    assert "智能体" not in sql
    assert "agent framework" not in sql
    assert len(database.cursor.calls) == 2


def test_lexical_lanes_placeholder_count_and_param_order_align() -> None:
    database = Database([[]])
    plan = ProjectLexicalRetrievalPlan(
        normalized_query="ai agent",
        strict_terms=("ai", "agent"),
        concepts=(
            ProjectLexicalConcept(
                concept_id="agent",
                primary_terms=("agent",),
                aliases=("智能体",),
            ),
        ),
    )

    PostgresProjectCatalogRepository(database).find_lexical_candidate_lanes(
        q=plan, category="agents", tag="llm", strict_limit=100, relaxed_limit=80,
    )

    sql, params = database.cursor.calls[1]
    # 每个 %s 占位符必须恰好绑定一个参数（契约见 postgres_project_catalog 参数顺序注释）。
    assert sql.count("%s") == len(params)
    # 1. filter_params：min_stars、category、tag（enriched 状态过滤无参数）
    assert params[:3] == (500, "agents", '%"llm"%')
    # 2. hit_params：term:0、term:1、concept:agent 各词/别名 × 两个文档分支，
    #    每行交错绑定 (group_id, pattern, group_id, pattern)
    assert params[3:19] == (
        "term:0", "%ai%", "term:0", "%ai%",
        "term:1", "%agent%", "term:1", "%agent%",
        "concept:agent", "%agent%", "concept:agent", "%agent%",
        "concept:agent", "%智能体%", "concept:agent", "%智能体%",
    )
    # 3. scored 匹配强度：normalized_query ×2（精确等值）+ prefix ×2（前缀）
    assert params[19:23] == ("ai agent", "ai agent", "ai agent%", "ai agent%")
    # 4. 车道边界：覆盖组数（term:0/term:1/concept:agent）、strict_limit、relaxed_limit
    assert params[23:] == (3, 100, 80)


def test_empty_typed_lexical_plan_short_circuits_without_transaction() -> None:
    database = Database([])
    plan = ProjectLexicalRetrievalPlan(normalized_query="", strict_terms=(), concepts=())

    assert not PostgresProjectCatalogRepository(database).find_lexical_candidate_lanes(q=plan).strict
    assert database.entered == 0


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


def test_plain_query_relevance_orders_by_name_and_title_match_strength() -> None:
    database = Database([{"cnt": 1}, []])
    PostgresProjectCatalogRepository(database).list_projects(
        q="langchain",
        sort="relevance",
        source="github",
    )
    rows_sql, rows_params = database.cursor.calls[2]
    assert "CASE WHEN LOWER(full_name)=LOWER(%s) THEN 0" in rows_sql
    assert "WHEN LOWER(COALESCE(title,''))=LOWER(%s) THEN 1" in rows_sql
    assert "WHEN full_name ILIKE %s ESCAPE '=' THEN 2" in rows_sql
    assert "WHEN COALESCE(title,'') ILIKE %s ESCAPE '=' THEN 3" in rows_sql
    assert "stars DESC, forks DESC, full_name ASC" in rows_sql
    assert rows_params.count("langchain") >= 2
    assert any(str(value) == "langchain%" for value in rows_params)


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
    assert item["tags_zh"] == ["AI", "docs"]
    assert item["tags_en"] == []
    assert item["tags_origin"] == "system"
    assert item["topics"] == ["web"]
    assert "tags_json" not in item and "topics_json" not in item
    assert item["stars"] == 0 and item["rank_in_period"] is None
    assert item["confidence"] == 0.5 and item["is_favorited"] is True
    assert item["favorited_at"] == "2026-01-02T03:04:00Z"
    assert item["category_slug"] == "other"
    assert item["subcategory_slug"] == "other_uncategorized"
    assert item["category_name"] == "其他网站"
    assert item["category_name_zh"] == "其他网站"
    assert item["category_name_en"] == "Other"
    assert item["subcategory_name"] == "未分类"
    assert item["subcategory_name_en"] == "Uncategorized"


def test_normalization_exposes_bilingual_system_tags_and_raw_user_tags() -> None:
    system = normalize_project_row({
        "tags_json": '["稳定值"]',
        "tags_zh_json": '["中文标签"]',
        "tags_en_json": '["English tag"]',
    })
    assert system["tags"] == ["稳定值"]
    assert system["tags_zh"] == ["中文标签"]
    assert system["tags_en"] == ["English tag"]
    assert system["tags_origin"] == "system"

    user = normalize_project_row({
        "tags_json": '["用户原文"]',
        "tags_zh_json": '["不应暴露"]',
        "tags_en_json": '["Must not leak"]',
        "tags_origin": "user",
    })
    assert user["tags"] == ["用户原文"]
    assert user["tags_zh"] == []
    assert user["tags_en"] == []
    assert user["tags_origin"] == "user"


def test_dynamic_category_formatting_preserves_taxonomy_and_defaults() -> None:
    result = format_project_category_counts([
        {"category_slug": "custom", "category_name": "Custom", "subcategory_slug": "x", "subcategory_name": "X", "count": 3},
        {"category_slug": "other", "category_name": "", "subcategory_slug": "", "subcategory_name": "", "count": 2},
    ])
    assert result["total"] == 5
    custom = result["items"][-1]
    assert custom["slug"] == "custom"
    assert custom["name"] == custom["name_zh"] == "Custom"
    assert custom["name_en"] == "Other"
    assert custom["children"] == [
        {"slug": "x", "name": "X", "name_zh": "X", "name_en": "x", "count": 3}
    ]


def test_public_github_list_projects_requires_active_availability_status() -> None:
    database = Database([{"cnt": 0}, []])
    PostgresProjectCatalogRepository(database).list_projects(source="github")
    for sql, _params in database.cursor.calls[1:]:
        assert "c.availability_status = 'active'" in sql


def test_lexical_candidate_repo_ids_requires_active_availability_status() -> None:
    database = Database([[{"repo_id": "owner/repo"}]])
    PostgresProjectCatalogRepository(database).find_lexical_candidate_repo_ids(q="agent")
    sql, _params = database.cursor.calls[1]
    assert "c.availability_status = 'active'" in sql


def test_lexical_candidate_lanes_eligible_requires_active_availability_status() -> None:
    database = Database([[]])
    PostgresProjectCatalogRepository(database).find_lexical_candidate_lanes(q="agent")
    sql, _params = database.cursor.calls[1]
    assert "c.availability_status = 'active'" in sql


def test_relevance_sort_uses_strong_field_match_branch() -> None:
    database = Database([{"cnt": 1}, []])
    PostgresProjectCatalogRepository(database).list_projects(
        q="word", sort="relevance", source="github"
    )
    count_sql, _count_params = database.cursor.calls[1]
    rows_sql, rows_params = database.cursor.calls[2]
    assert "has_strong_match" in count_sql
    assert "has_strong_match" in rows_sql
    assert "total_strong" in count_sql
    assert "total_strong" in rows_sql
    assert RELEVANCE_STRONG_MATCH_THRESHOLD in rows_params
    # 强字段：仓库名、标题、系统标签（含 i18n）。
    assert "c.full_name ILIKE %s ESCAPE '='" in rows_sql
    assert "c.title ILIKE %s ESCAPE '='" in rows_sql
    assert "ge.tags_json::text" in rows_sql
    # 弱字段（描述、语言、topics）仍在 WHERE 中用于 broad 集合，但不参与 has_strong_match。
    assert "c.description ILIKE %s ESCAPE '='" in rows_sql
    assert "c.topics_json" in rows_sql
    assert "COALESCE(c.language, '')" in rows_sql


def test_non_relevance_sort_retains_broad_keyword_filter() -> None:
    database = Database([{"cnt": 1}, []])
    PostgresProjectCatalogRepository(database).list_projects(
        q="word", sort="stars", source="github"
    )
    rows_sql, _rows_params = database.cursor.calls[2]
    assert "has_strong_match" not in rows_sql
    assert "c.description ILIKE %s ESCAPE '='" in rows_sql
    assert "c.topics_json" in rows_sql
    assert "COALESCE(c.language, '')" in rows_sql


def test_empty_query_does_not_add_strong_match_column() -> None:
    database = Database([{"cnt": 0}, []])
    PostgresProjectCatalogRepository(database).list_projects(sort="relevance", source="github")
    rows_sql, _rows_params = database.cursor.calls[2]
    assert "has_strong_match" not in rows_sql


def test_strong_match_threshold_zero_when_query_yields_no_terms() -> None:
    # 传输词/单字符/纯符号查询提取不出搜索词：阈值必须归零，
    # 否则空强命中条件会折叠成 (())::boolean 非法 SQL（公开接口 500）
    for query in ("github", "项目", "a", "!!!"):
        assert _strong_match_threshold("relevance", query, None) == 0
    assert _strong_match_threshold("relevance", "word", None) == RELEVANCE_STRONG_MATCH_THRESHOLD
    assert _strong_match_threshold("stars", "word", None) == 0
    assert _strong_match_threshold("relevance", "word", ["acme/alpha"]) == 0


def test_strong_match_clause_folds_empty_conditions_to_false_defensively() -> None:
    assert _strong_match_clause([]) == "FALSE::boolean has_strong_match"
    assert _strong_match_clause(["c.full_name ILIKE %s ESCAPE '='"]) == (
        "((c.full_name ILIKE %s ESCAPE '='))::boolean has_strong_match"
    )


def test_empty_term_relevance_search_returns_empty_page_without_strong_match_sql() -> None:
    for query in ("github", "a", "!!!", "项目"):
        database = Database([{"cnt": 0}, []])
        result = PostgresProjectCatalogRepository(database).list_projects(
            q=query, sort="relevance"
        )
        assert result == {"items": [], "total": 0, "page": 1, "page_size": 24}
        count_sql = database.cursor.calls[1][0]
        rows_sql = database.cursor.calls[2][0]
        # 空搜索词：强命中过滤整体关闭，绝不出现 (())::boolean 非法片段
        assert "(())" not in count_sql
        assert "(())" not in rows_sql
        assert "has_strong_match" not in count_sql
        assert "has_strong_match" not in rows_sql
        # 与 filters=FALSE 早退路径对齐：两个分支恒假，结果必为空
        assert "FALSE" in count_sql


def test_categories_favorites_reuse_list_visibility_predicate() -> None:
    database = Database([[], {"count": 0}, {"count": 0}])
    PostgresProjectCatalogRepository(database).get_project_categories(
        source="website", user_id=7, favorites_only=True, enriched_only=True
    )
    aggregate_sql, aggregate_params = database.cursor.calls[1]
    today_sql, today_params = database.cursor.calls[2]
    recommended_sql = database.cursor.calls[3][0]
    for sql in (aggregate_sql, today_sql):
        # 与 list_projects 收藏夹分支同一可见性口径：
        # LEFT JOIN 富化表 + 自建/覆盖可见的 OR 谓词
        assert "LEFT JOIN tool_website_enrichments we ON we.website_id=w.id" in sql
        assert "user_tool_website_overrides uo" in sql
        assert "(we.status='succeeded' OR uo.id IS NOT NULL OR utw.id IS NOT NULL)" in sql
        assert "(pf.id IS NOT NULL OR utw.id IS NOT NULL)" in sql
        assert "w.visibility='public'" not in sql
    assert aggregate_params.count(7) == 3
    assert today_params.count(7) == 3
    # 分组键沿用列表 effective 分类表达式（用户覆盖优先）
    assert "COALESCE(NULLIF(uo.category_slug, ''), we.category_slug)" in aggregate_sql
    assert recommended_sql == "SELECT 0 count"


def test_categories_public_branch_keeps_inner_join_enrichment() -> None:
    database = Database([[], {"count": 0}, {"count": 0}])
    PostgresProjectCatalogRepository(database).get_project_categories(source="website")
    aggregate_sql = database.cursor.calls[1][0]
    assert "JOIN tool_website_enrichments we ON we.website_id=w.id" in aggregate_sql
    assert "LEFT JOIN tool_website_enrichments" not in aggregate_sql
    assert "we.status='succeeded'" in aggregate_sql
    assert "w.visibility='public'" in aggregate_sql


def test_union_branches_align_daily_growth_observed_at_column_type() -> None:
    database = Database([{"cnt": 0}, []])
    PostgresProjectCatalogRepository(database).list_projects(source="all")
    rows_sql = database.cursor.calls[2][0]
    # gm.daily_growth_observed_at 在 schema 中是 TEXT：website 分支占位必须同为
    # text，否则 UNION ALL 报类型不匹配，source=all（公开列表默认）整表 500
    assert "NULL::text daily_growth_observed_at" in rows_sql
    assert "NULL::timestamptz daily_growth_observed_at" not in rows_sql


def test_union_branches_align_license_column_type() -> None:
    database = Database([{"cnt": 0}, []])
    PostgresProjectCatalogRepository(database).list_projects(source="all")
    rows_sql = database.cursor.calls[2][0]
    # license 只在 github 分支有源列；website 分支必须补同型 text 占位，
    # 否则 UNION ALL 类型不匹配
    assert "c.license_spdx_id" in rows_sql
    assert "NULL::text license_spdx_id" in rows_sql
