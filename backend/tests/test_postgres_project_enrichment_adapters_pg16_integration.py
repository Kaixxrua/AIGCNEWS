from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any, Iterator

import pytest

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
    from backend.app.repositories.postgres_project_enrichment_repository import (
        PostgresGitHubProjectEnrichmentRepository,
        PostgresToolWebsiteEnrichmentRepository,
    )
finally:
    os.chdir(_IMPORT_CWD)


def _test_dsn() -> str:
    dsn = os.environ.get("TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("TEST_POSTGRES_DSN is required for PostgreSQL integration tests")
    database = str(conninfo_to_dict(dsn).get("dbname") or "")
    if "test" not in database.lower():
        pytest.skip("TEST_POSTGRES_DSN dbname must contain 'test'")
    return dsn


@pytest.fixture(scope="module")
def repositories() -> Iterator[tuple[Any, Any, Any]]:
    dsn = _test_dsn()
    schema = f"enrichment_pg16_{uuid.uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        version = int(admin.execute("SHOW server_version_num").fetchone()[0])
        if version < 160000 or version >= 170000:
            pytest.skip("this integration suite requires PostgreSQL 16")
        admin.execute(f'CREATE SCHEMA "{schema}"')
    scoped_dsn = make_conninfo(dsn, options=f"-c search_path={schema}")
    database = PostgresDatabaseLifecycle(lambda: ConnectionPool(
        conninfo=scoped_dsn, min_size=1, max_size=4, timeout=10,
        kwargs={"autocommit": False, "row_factory": psycopg.rows.dict_row}, open=False,
    ))
    try:
        PostgresMigrationRunner(database).apply()
        yield database, PostgresGitHubProjectEnrichmentRepository(database), PostgresToolWebsiteEnrichmentRepository(database)
    finally:
        database.close()
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def test_pg16_github_candidates_fingerprint_status_and_alias_upsert(repositories) -> None:
    database, github, _ = repositories
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""INSERT INTO github_repo_candidates
                (repo_id,full_name,description,language,topics_json,stars,forks,watchers)
                VALUES ('canonical','acme/agent','Agent','Python','[\"rag\"]',600,2,3),
                       ('new','acme/new','New','Go','[]',550,1,1)""")
            cursor.execute("""INSERT INTO github_repo_aliases
                (alias_repo_id,canonical_repo_id,full_name) VALUES ('alias','canonical','old/agent')""")
            cursor.execute("""INSERT INTO github_repo_snapshots
                (repo_id,snapshot_date,captured_at,stars,forks,watchers,open_issues)
                VALUES ('canonical','2026-07-27','now',700,4,5,6),
                       ('canonical','2026-07-28','now',800,7,8,9)""")
    candidates = github.get_github_projects_needing_enrichment(limit=10)
    assert [row["repo_id"] for row in candidates] == ["canonical", "new"]
    assert candidates[0]["stars"] == 800
    assert candidates[0]["topics"] == ["rag"]
    fingerprint = candidates[0]["source_fingerprint"]

    github.upsert_github_repo_enrichment({
        "repo_id": "alias", "category_slug": "agent", "category_name": "Agent",
        "description_zh": "智能体", "tags": ["RAG"], "source_fingerprint": fingerprint,
        "prompt_version": "v1",
    })
    assert [row["repo_id"] for row in github.get_github_projects_needing_enrichment()] == ["new"]
    github.mark_github_repo_enrichment_failed(
        "new", source_fingerprint=candidates[1]["source_fingerprint"],
        prompt_version="v1", error_msg="boom"
    )
    assert github.get_github_project_enrichment_status() == {
        "eligible": 2, "succeeded": 1, "failed": 1, "pending": 0,
        "by_category": [{"slug": "agent", "name": "Agent", "count": 1}],
    }
    assert [row["repo_id"] for row in github.get_github_projects_needing_enrichment(retry_failed=True)] == ["new"]


def test_pg16_website_metadata_merge_item_and_enrichment_failure(repositories) -> None:
    _, _, websites = repositories
    created = websites.upsert_tool_website({
        "canonical_url": "https://tool.test/docs", "normalized_url_hash": "h" * 64,
        "domain": "tool.test", "title": "Tool", "description": "Useful",
        "image_url": "https://tool.test/logo.png", "raw_metadata_json": '{"a":1}',
        "source_fingerprint": "a" * 64, "visibility": "private",
    })
    merged = websites.upsert_tool_website({
        "canonical_url": "https://tool.test", "normalized_url_hash": "h" * 64,
        "domain": "tool.test", "title": "", "description": "", "image_url": "",
        "source_fingerprint": "b" * 64, "visibility": "public",
    })
    assert merged["id"] == created["id"]
    assert merged["title"] == "Tool"
    assert merged["description"] == "Useful"
    assert merged["visibility"] == "public"

    websites.upsert_tool_website_enrichment({
        "website_id": created["id"], "category_slug": "ai_tools",
        "category_name": "AI 工具", "description_zh": "工具", "tags": ["AI"],
        "source_fingerprint": "b" * 64, "prompt_version": "v1",
    })
    item = websites.get_tool_website_item(created["id"])
    assert item is not None
    assert item["id"] == f"website:{created['id']}"
    assert item["tags"] == ["AI"]
    assert item["image_url"] == "https://tool.test/logo.png"

    websites.mark_tool_website_enrichment_failed(
        created["id"], source_fingerprint="c" * 64,
        prompt_version="v2", error_msg="x" * 2100,
    )
    failed = websites.get_tool_website_enrichment(created["id"])
    assert failed is not None
    assert failed["status"] == "failed"
    assert len(failed["error_msg"]) == 2000
