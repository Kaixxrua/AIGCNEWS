from __future__ import annotations

import importlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Iterator

import pytest

from backend.app.repositories.project_catalog import (
    ProjectLexicalConcept,
    ProjectLexicalRetrievalPlan,
)

# Import application settings away from the repository root so pydantic cannot
# discover a developer or production-like .env file during this opt-in test.
_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from psycopg_pool import ConnectionPool

    from backend.app.core.postgres_database import PostgresDatabaseLifecycle
    from backend.app.core.postgres_migrations import PostgresMigrationRunner
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
    "stars",
    "forks",
    "pushed_at",
    "daily_star_growth",
    "daily_growth_available",
    "hot_score",
    "is_recommended",
    "result_origin",
}


def _test_dsn() -> str:
    dsn = os.environ.get("TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is required for PostgreSQL integration tests")
    try:
        database = str(conninfo_to_dict(dsn).get("dbname") or "")
    except Exception as exc:
        pytest.skip(f"TEST_POSTGRES_DSN is not a valid PostgreSQL DSN: {exc}")
    if "test" not in database.lower():
        pytest.skip("TEST_POSTGRES_DSN dbname must contain 'test'")
    return dsn


@pytest.fixture(scope="module")
def catalog() -> Iterator[Any]:
    dsn = _test_dsn()
    schema = f"catalog_it_{uuid.uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f'CREATE SCHEMA "{schema}"')

    scoped_dsn = make_conninfo(dsn, options=f"-c search_path={schema}")
    database = PostgresDatabaseLifecycle(
        lambda: ConnectionPool(
            conninfo=scoped_dsn,
            min_size=1,
            max_size=4,
            timeout=10,
            kwargs={"autocommit": False, "row_factory": psycopg.rows.dict_row},
            open=False,
        )
    )
    try:
        applied = PostgresMigrationRunner(database).apply()
        assert applied, "a unique schema must receive the committed migrations"
        with database.transaction() as connection:
            connection.execute(SEED_PATH.read_text(encoding="utf-8"))

        try:
            adapter_module = importlib.import_module(
                "backend.app.repositories.postgres_project_catalog"
            )
        except ModuleNotFoundError as exc:
            if exc.name == "backend.app.repositories.postgres_project_catalog":
                pytest.skip("PostgresProjectCatalogRepository is not available yet")
            raise
        repository_type = adapter_module.PostgresProjectCatalogRepository
        try:
            yield repository_type(database=database)
        except TypeError:
            yield repository_type(database)
    finally:
        database.close()
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def test_real_catalog_queries_match_committed_expected_results(catalog: Any) -> None:
    result = catalog.list_projects(
        source="github", min_stars=500, enriched_only=True, sort="stars"
    )

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

    recommended = catalog.list_projects(
        source="github", scope="recommended", min_stars=500
    )
    assert [item["repo_id"] for item in recommended["items"]] == ["acme/alpha"]

    favorites = catalog.list_projects(
        source="github", min_stars=500, user_id=42, favorites_only=True
    )
    assert [item["repo_id"] for item in favorites["items"]] == ["acme/beta"]
    assert favorites["items"][0]["is_favorited"] is True

    categories = catalog.get_project_categories(source="github", min_stars=500)
    assert categories["total"] == 2
    assert categories["today_count"] == 2
    assert categories["recommended_count"] == 1
    counts = {item["slug"]: item["count"] for item in categories["items"]}
    assert counts["rag_knowledge"] == 1
    assert counts["agents_automation"] == 1


def test_real_rows_preserve_serialization_and_mcp_contract(catalog: Any) -> None:
    from backend.app.services.mcp.inbound.responses import _tool_response

    row = catalog.list_projects(
        source="github", category="rag_knowledge", min_stars=500
    )["items"][0]
    public = public_project_item(row)
    response = _tool_response({"items": [public], "total": 1})

    assert set(public) == EXPECTED_PUBLIC_FIELDS
    assert response["isError"] is False
    assert response["content"] == [
        {
            "type": "text",
            "text": json.dumps(response["structuredContent"], ensure_ascii=False),
        }
    ]
    assert json.loads(response["content"][0]["text"]) == response["structuredContent"]
    assert response["structuredContent"]["items"][0]["id"] == "github:acme/alpha"
    assert "repo_id" not in response["structuredContent"]["items"][0]


def test_real_catalog_empty_term_relevance_search_returns_empty_page(catalog: Any) -> None:
    # 传输词/单字符/纯符号查询提取不出搜索词：此前强命中空条件折叠成
    # (())::boolean 非法 SQL，公开接口 500；现在与 filters=FALSE 早退对齐
    for query in ("github", "a", "!!!", "项目"):
        result = catalog.list_projects(q=query, sort="relevance", min_stars=0)
        assert result["total"] == 0
        assert result["items"] == []
        assert result["page"] == 1
        assert result["page_size"] == 24


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
            "INSERT INTO user_tool_websites (user_id, website_id, added_via)"
            " VALUES (42, %s, 'manual')",
            (website_id,),
        )
        connection.execute(
            "INSERT INTO project_favorites (user_id, project_source, project_id)"
            " VALUES (42, 'website', %s)",
            (str(website_id),),
        )

    listed = catalog.list_projects(
        source="website", user_id=42, favorites_only=True, min_stars=0
    )
    assert listed["total"] == 1
    assert [item["domain"] for item in listed["items"]] == ["selfhost.example"]
    assert listed["items"][0]["is_favorited"] is True
    assert listed["items"][0]["category_slug"] == "other"

    categories = catalog.get_project_categories(
        source="website", user_id=42, favorites_only=True
    )
    # 修复前此处为 0（INNER JOIN 富化表把未富化自建网站排除在计数外）
    assert categories["total"] == listed["total"]
    counts = {item["slug"]: item["count"] for item in categories["items"]}
    assert counts.get("other") == 1
