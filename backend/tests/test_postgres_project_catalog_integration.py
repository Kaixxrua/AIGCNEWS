from __future__ import annotations

import importlib
import os
from datetime import date, datetime, tzinfo
from pathlib import Path
from typing import Any, Iterator

import pytest

from backend.app.repositories.project_catalog import (
    ProjectLexicalConcept,
    ProjectLexicalRetrievalPlan,
)
from backend.tests.postgres_test_safety import postgres_test_sandbox

# Import application settings away from the repository root so pydantic cannot
# discover a developer or production-like .env file during this opt-in test.
_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")

    from backend.app.services.project_discovery import public_project_item
finally:
    os.chdir(_IMPORT_CWD)

SEED_PATH = _TESTS_DIR / "fixtures" / "postgres_catalog_seed.sql"
EXPECTED_PUBLIC_FIELDS = {
    "id",
    "full_name",
    "url",
    "description",
    "description_zh",
    "description_en",
    "category_slug",
    "category_name",
    "category_name_zh",
    "category_name_en",
    "subcategory_slug",
    "subcategory_name",
    "subcategory_name_zh",
    "subcategory_name_en",
    "tags",
    "tags_zh",
    "tags_en",
    "tags_origin",
    "topics",
    "language",
    "license",
    "stars",
    "forks",
    "pushed_at",
    "daily_star_growth",
    "daily_growth_available",
    "hot_score",
    "growth_suspicion_score",
    "is_recommended",
    "result_origin",
}


@pytest.fixture(scope="module", params=[
    ("2026-09-18T15:59:00+00:00", "2026-09-18"),
    ("2026-09-18T16:01:00+00:00", "2026-09-19"),
    ("2026-12-31T16:01:00+00:00", "2027-01-01"),
], ids=["before-shanghai-midnight", "after-shanghai-midnight", "shanghai-new-year"])
def catalog_clock(request: pytest.FixtureRequest) -> tuple[datetime, date]:
    instant, business_date = request.param
    return datetime.fromisoformat(instant), date.fromisoformat(business_date)


@pytest.fixture(scope="module")
def catalog(catalog_clock: tuple[datetime, date]) -> Iterator[Any]:
    instant, business_date = catalog_clock
    adapter_module = importlib.import_module("backend.app.repositories.postgres_project_catalog")

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> "FrozenDateTime":
            return cls.fromtimestamp(instant.timestamp(), tz)

    # Freeze the input clock, not _today(): exercise the real business timezone
    # conversion, independent of the host clock and the database session zone.
    with pytest.MonkeyPatch.context() as patch, postgres_test_sandbox() as sandbox:
        patch.setattr(adapter_module, "datetime", FrozenDateTime)
        patch.setattr(adapter_module.settings, "scheduler_timezone", "Asia/Shanghai")
        assert adapter_module._today() == business_date.isoformat()
        database = sandbox.database
        with database.transaction() as connection:
            connection.execute("SET LOCAL TIME ZONE 'UTC'")
            connection.execute(psycopg.sql.SQL(SEED_PATH.read_text(encoding="utf-8")).format(
                metric_date=psycopg.sql.Literal(business_date),
            ))
        yield adapter_module.PostgresProjectCatalogRepository(database=database)


def test_seed_date_matches_business_day_in_utc_database(
    catalog: Any, catalog_clock: tuple[datetime, date],
) -> None:
    instant, business_date = catalog_clock
    with catalog._database.transaction() as connection:
        connection.execute("SET LOCAL TIME ZONE 'UTC'")
        row = connection.execute(
            "SELECT (%s::timestamptz AT TIME ZONE 'UTC')::date AS utc_date, "
            "(%s::timestamptz AT TIME ZONE 'Asia/Shanghai')::date AS business_date",
            (instant, instant),
        ).fetchone()
        metrics = connection.execute(
            "SELECT metric_date::date AS metric_date, "
            "previous_snapshot_date::date AS previous_snapshot_date FROM github_repo_daily_metrics"
        ).fetchall()
    assert row["business_date"] == business_date
    assert row["utc_date"] == instant.date()
    assert (row["utc_date"] != business_date) == (instant.hour >= 16)
    assert len(metrics) == 2
    assert all(item["metric_date"] == business_date for item in metrics)
    assert all((item["metric_date"] - item["previous_snapshot_date"]).days == 1 for item in metrics)


def test_real_catalog_queries_match_committed_expected_results(catalog: Any) -> None:
    result = catalog.list_projects(source="github", min_stars=500, enriched_only=True, sort="stars")

    assert result["total"] == 2
    assert result["page"] == 1
    assert result["page_size"] == 24
    assert [item["repo_id"] for item in result["items"]] == ["acme/alpha", "acme/beta"]
    assert result["items"][0]["tags"] == ["RAG", "local"]
    assert result["items"][0]["topics"] == ["rag", "knowledge-base"]
    assert result["items"][0]["daily_star_growth"] == 42
    assert result["items"][0]["daily_growth_available"] is True
    assert result["items"][0]["is_recommended"] is True

    filtered = catalog.list_projects(
        source="github",
        q="workflow runtime",
        language="typescript",
        tag="MCP",
        min_stars=500,
        enriched_only=True,
    )
    assert filtered["total"] == 1
    assert [item["repo_id"] for item in filtered["items"]] == ["acme/beta"]

    hydrated = catalog.list_projects(
        source="all",
        min_stars=0,
        candidate_repo_ids=["acme/beta", "acme/alpha", "acme/beta"],
    )
    assert hydrated["total"] == 2
    assert [item["repo_id"] for item in hydrated["items"]] == ["acme/alpha", "acme/beta"]

    lanes = catalog.find_lexical_candidate_lanes(
        q="workflow local",
        min_stars=500,
        enriched_only=True,
    )
    assert [item.repo_id for item in lanes.strict] == []
    assert [item.repo_id for item in lanes.relaxed] == ["acme/alpha", "acme/beta"]
    assert [item.term_coverage for item in lanes.relaxed] == [1, 1]


def test_real_catalog_typed_concepts_match_aliases_once_per_group(catalog: Any) -> None:
    plan = ProjectLexicalRetrievalPlan(
        normalized_query="local agent runtime",
        strict_terms=("local",),
        concepts=(
            ProjectLexicalConcept(
                concept_id="agent",
                primary_terms=("智能体",),
                aliases=("agent", "workflow"),
            ),
        ),
    )

    lanes = catalog.find_lexical_candidate_lanes(
        q=plan,
        min_stars=500,
        enriched_only=True,
    )

    assert [item.repo_id for item in lanes.strict] == []
    assert [item.repo_id for item in lanes.relaxed] == ["acme/alpha", "acme/beta"]
    assert [item.term_coverage for item in lanes.relaxed] == [1, 1]


def test_real_catalog_scope_favorites_and_categories(catalog: Any) -> None:
    today = catalog.list_projects(source="github", scope="today", min_stars=500)
    assert [item["repo_id"] for item in today["items"]] == ["acme/alpha", "acme/beta"]

    recommended = catalog.list_projects(source="github", scope="recommended", min_stars=500)
    assert [item["repo_id"] for item in recommended["items"]] == ["acme/alpha"]

    favorites = catalog.list_projects(source="github", min_stars=500, user_id=42, favorites_only=True)
    assert [item["repo_id"] for item in favorites["items"]] == ["acme/beta"]
    assert favorites["items"][0]["is_favorited"] is True

    categories = catalog.get_project_categories(source="github", min_stars=500)
    assert categories["total"] == 2
    assert categories["today_count"] == 2
    assert categories["recommended_count"] == 1
    counts = {item["slug"]: item["count"] for item in categories["items"]}
    assert counts["rag_knowledge"] == 1
    assert counts["agents_automation"] == 1


def test_real_rows_preserve_public_serialization(catalog: Any) -> None:
    row = catalog.list_projects(source="github", category="rag_knowledge", min_stars=500)["items"][0]
    public = public_project_item(row)

    assert set(public) == EXPECTED_PUBLIC_FIELDS
    assert public["id"] == "github:acme/alpha"
    assert "repo_id" not in public


def test_real_catalog_empty_term_relevance_search_returns_empty_page(catalog: Any) -> None:
    # 传输词/单字符/纯符号查询提取不出搜索词：此前强命中空条件折叠成
    # (())::boolean 非法 SQL，公开接口 500；现在与 filters=FALSE 早退对齐
    for query in ("github", "a", "!!!", "项目"):
        result = catalog.list_projects(q=query, sort="relevance", min_stars=0)
        assert result["total"] == 0
        assert result["items"] == []
        assert result["page"] == 1
        assert result["page_size"] == 24


def test_real_repo_name_segment_outranks_owner_prefix(catalog: Any) -> None:
    """裸仓库名搜索：名段等值必须压过 full_name 整体前缀（earendil-works/pi 契约）。

    pintail-owner/other 的 full_name 以查询词开头（旧逻辑的高层级），
    someone/pintail 仅名段恰好等于查询词；名段层级上线后后者必须排第一，
    即使前者星数高三个数量级。title 刻意避开精确/前缀命中，保证区分度
    只来自名段。
    """
    database = catalog._database
    candidates_sql = """
        INSERT INTO github_repo_candidates (
            repo_id, full_name, title, url, description, language, topics_json,
            created_at, pushed_at, stars, forks, watchers, source_channels,
            first_seen_at, last_seen_at, last_snapshot_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    enrichment_sql = """
        INSERT INTO github_repo_enrichments (
            repo_id, category_slug, category_name, subcategory_slug, subcategory_name,
            description_zh, tags_json, confidence, source_fingerprint, prompt_version,
            model_provider, model_name, status, enriched_at, updated_at
        ) VALUES (%s, 'rag_knowledge', 'RAG 与知识库', 'rag_framework', 'RAG 框架',
                  '夹具', '[]', 0.9, repeat('c', 64), 'fixture-v1',
                  'fixture', 'fixture', 'succeeded', '2026-07-23T08:00:00Z', '2026-07-23T08:00:00Z')
    """

    def insert_candidate(repo_id: str, title: str, stars: int) -> None:
        with database.transaction() as connection:
            connection.execute(
                candidates_sql,
                (
                    repo_id,
                    repo_id,
                    title,
                    f"https://github.com/{repo_id}",
                    "name segment fixture",
                    "Python",
                    "[]",
                    "2025-01-01T00:00:00Z",
                    "2026-07-20T08:00:00Z",
                    stars,
                    1,
                    1,
                    "fixture",
                    "2026-07-01T00:00:00Z",
                    "2026-07-20T08:00:00Z",
                    "2026-07-23T09:00:00Z",
                ),
            )
            connection.execute(enrichment_sql, (repo_id,))

    extra_ids = ("pintail-owner/other", "someone/pintail", "second/pintail")
    try:
        insert_candidate("pintail-owner/other", "Other", 900000)
        insert_candidate("someone/pintail", "Someone Pintail", 600)

        lanes = catalog.find_lexical_candidate_lanes(q="pintail", min_stars=500)
        assert [item.repo_id for item in lanes.strict] == ["someone/pintail", "pintail-owner/other"]
        assert [item.match_strength for item in lanes.strict] == [5, 2]

        flat = catalog.find_lexical_candidate_repo_ids(q="pintail", min_stars=500)
        assert flat[:2] == ["someone/pintail", "pintail-owner/other"]

        page = catalog.list_projects(source="github", q="pintail", sort="relevance", min_stars=500)
        assert [item["repo_id"] for item in page["items"]] == ["someone/pintail", "pintail-owner/other"]

        # 裸名唯一命中：钉顶查询只回一个；第二个同名仓库出现后唯一性消失
        assert catalog.find_repo_ids_by_name_segment(name="pintail") == ["someone/pintail"]
        insert_candidate("second/pintail", "Pintail Two", 550)
        assert catalog.find_repo_ids_by_name_segment(name="pintail") == ["someone/pintail", "second/pintail"]
    finally:
        with database.transaction() as connection:
            connection.execute(
                "DELETE FROM github_repo_candidates WHERE repo_id = ANY(%s)",
                (list(extra_ids),),
            )


def test_real_favorites_visibility_matches_category_counts(catalog: Any) -> None:
    # 收藏未富化的自建网站：列表可见（utw/uo 口径），分类计数必须同口径
    with catalog._database.transaction() as connection:
        row = connection.execute(
            """
            INSERT INTO tool_websites (
                canonical_url, normalized_url_hash, domain, title, description,
                source_fingerprint, visibility, added_by_user_id,
                first_seen_at, last_seen_at, updated_at
            ) VALUES (
                'https://selfhost.example/', repeat('d', 64), 'selfhost.example',
                'Selfhost Tool', 'user added unenriched site',
                repeat('e', 64), 'private', 42,
                '2026-07-23T09:00:00Z', '2026-07-23T09:00:00Z', '2026-07-23T09:00:00Z'
            ) RETURNING id
            """
        ).fetchone()
        website_id = int(row["id"])
        connection.execute(
            "INSERT INTO user_tool_websites (user_id, website_id, added_via) VALUES (42, %s, 'manual')",
            (website_id,),
        )
        connection.execute(
            "INSERT INTO project_favorites (user_id, project_source, project_id) VALUES (42, 'website', %s)",
            (str(website_id),),
        )

    listed = catalog.list_projects(source="website", user_id=42, favorites_only=True, min_stars=0)
    assert listed["total"] == 1
    assert [item["domain"] for item in listed["items"]] == ["selfhost.example"]
    assert listed["items"][0]["is_favorited"] is True
    assert listed["items"][0]["category_slug"] == "other"

    categories = catalog.get_project_categories(source="website", user_id=42, favorites_only=True)
    # 修复前此处为 0（INNER JOIN 富化表把未富化自建网站排除在计数外）
    assert categories["total"] == listed["total"]
    counts = {item["slug"]: item["count"] for item in categories["items"]}
    assert counts.get("other") == 1


def test_real_github_hot_board_reads_v5_metrics(catalog: Any, catalog_clock: tuple[datetime, date]) -> None:
    # 看板 github 今日暴涨榜：公开口径为 succeeded canonical + active + 正增长
    # （无星数门槛），hot_score(v5) 降序；夹具中 acme/draft 无增强无指标，永不出现。
    today = catalog_clock[1].isoformat()
    rows = catalog.list_github_hot_for_date(metric_date=today, limit=10)

    assert [row["repo_id"] for row in rows] == ["acme/alpha", "acme/beta"]
    first = rows[0]
    assert first["full_name"] == "acme/alpha"
    assert first["url"] == "https://github.com/acme/alpha"
    assert first["description"] == "Local RAG workspace"
    assert first["description_zh"] == "本地知识库"
    assert "description_en" in first
    assert first["language"] == "Python"
    assert first["topics_json"] == '["rag", "knowledge-base"]'
    assert first["stars"] == 1200
    assert first["daily_star_growth"] == 42
    assert first["daily_growth_source"] == "snapshot_delta"
    assert first["hot_score"] == 91.5
    assert first["metric_date"] == today
    # 反作弊打标列默认值透出（夹具未写入即 0/[]/FALSE）
    assert first["growth_suspicion_score"] == 0.0
    assert first["growth_suspicion_signals"] == "[]"
    assert first["growth_corroborated"] is False

    # 公开榜无星数门槛：已成功富化的项目即使显式传 min_stars=1000 也保留
    # （跌破门槛的成功存量不从公开口径消失）
    assert [
        row["repo_id"] for row in catalog.list_github_hot_for_date(metric_date=today, limit=10, min_stars=1000)
    ] == ["acme/alpha", "acme/beta"]
    # 星数门槛只保留给非公开（intake/未成功队列）口径：1000 以上只剩 alpha
    # （draft 无当日指标，永不出现）
    assert [
        row["repo_id"]
        for row in catalog.list_github_hot_for_date(metric_date=today, limit=10, min_stars=1000, enriched_only=False)
    ] == ["acme/alpha"]
    # 无指标日期返回空（诚实空榜，不回退）
    assert catalog.list_github_hot_for_date(metric_date="1999-01-01", limit=10) == []

    dates = catalog.list_github_hot_dates(limit=5)
    assert today in dates
    assert dates == sorted(dates, reverse=True)


def test_real_today_board_prefers_rolling_growth_over_daily(
    catalog: Any, catalog_clock: tuple[datetime, date],
) -> None:
    # 热度 v8：滚动 24h 可得时以它判定正增长并排序，取不到窗口起点才退回日增量；
    # 看板日榜、项目库今日榜、今日计数三处同一口径。
    today = catalog_clock[1].isoformat()

    def board() -> tuple[list[str], list[str], int]:
        return (
            [row["repo_id"] for row in catalog.list_github_hot_for_date(metric_date=today, limit=10)],
            [item["repo_id"] for item in catalog.list_projects(
                source="github", scope="today", min_stars=500)["items"]],
            catalog.get_project_categories(source="github", min_stars=500)["today_count"],
        )

    def set_beta(**fields: Any) -> None:
        assignments = ", ".join(f"{column} = %s" for column in fields)
        with catalog._database.transaction() as connection:
            connection.execute(
                f"UPDATE github_repo_daily_metrics SET {assignments}"
                " WHERE repo_id = 'acme/beta' AND metric_date = %s",
                (*fields.values(), today),
            )

    try:
        # 日增为正、但滚动窗口明确为 0：热度已归零，下榜
        set_beta(rolling_24h_star_growth=0, rolling_24h_growth_source="rolling_window")
        assert board() == (["acme/alpha"], ["acme/alpha"], 1)
        # 无前日快照（日增不可得）、只有滚动增长的新仓：上榜并透出滚动字段
        set_beta(daily_growth_available=False, daily_star_growth=0,
                 rolling_24h_star_growth=30, rolling_24h_growth_source="since_creation",
                 rolling_24h_observed_at=f"{today}T01:00:00+00:00")
        assert board() == (["acme/alpha", "acme/beta"], ["acme/alpha", "acme/beta"], 2)
        beta = next(item for item in catalog.list_projects(
            source="github", scope="today", min_stars=500)["items"] if item["repo_id"] == "acme/beta")
        assert beta["rolling_24h_star_growth"] == 30
        assert beta["rolling_24h_growth_source"] == "since_creation"
        assert beta["rolling_24h_observed_at"] == f"{today}T01:00:00+00:00"
        hot_row = catalog.list_github_hot_for_date(metric_date=today, limit=10)[1]
        assert hot_row["rolling_24h_star_growth"] == 30
        assert hot_row["rolling_24h_growth_source"] == "since_creation"
    finally:
        set_beta(daily_growth_available=True, daily_star_growth=12, rolling_24h_star_growth=None,
                 rolling_24h_growth_source=None, rolling_24h_observed_at=None)
    alpha = next(item for item in catalog.list_projects(
        source="github", scope="today", min_stars=500)["items"] if item["repo_id"] == "acme/alpha")
    assert alpha["rolling_24h_star_growth"] is None


def _shift_metric_dates(catalog: Any, days: int) -> None:
    with catalog._database.transaction() as connection:
        connection.execute(
            "UPDATE github_repo_daily_metrics"
            " SET metric_date = (metric_date::date + %s)::text",
            (days,),
        )


def test_real_today_scope_uses_yesterday_until_first_round(catalog: Any) -> None:
    # 零点后当天首轮指标落库前，今日榜/今日计数/hot 排序沿用昨天的收盘切片；
    # 只回退一天：前天的指标不冒充今日。
    shifted = 0
    try:
        _shift_metric_dates(catalog, -1)
        shifted = -1
        today = catalog.list_projects(source="github", scope="today", min_stars=500)
        assert [item["repo_id"] for item in today["items"]] == ["acme/alpha", "acme/beta"]
        assert catalog.get_project_categories(source="github", min_stars=500)["today_count"] == 2
        hot = catalog.list_projects(source="github", sort="hot", min_stars=500)
        assert [item["hot_score"] for item in hot["items"]][:2] == [91.5, 70.0]
        _shift_metric_dates(catalog, -1)
        shifted = -2
        assert catalog.list_projects(source="github", scope="today", min_stars=500)["items"] == []
        assert catalog.get_project_categories(source="github", min_stars=500)["today_count"] == 0
    finally:
        if shifted:
            _shift_metric_dates(catalog, -shifted)


def test_real_popularity_map_sums_window_growth(catalog: Any) -> None:
    popularity = catalog.get_project_popularity_map(["acme/alpha", "acme/beta", "acme/draft", "missing/repo"])
    assert popularity["acme/alpha"] == (42, 1200)
    assert popularity["acme/beta"] == (12, 800)
    assert popularity["acme/draft"][0] == 0
    assert "missing/repo" not in popularity
