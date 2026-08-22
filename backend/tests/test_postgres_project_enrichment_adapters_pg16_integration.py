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
            # renamed_old：改名墓碑行（旧名候选行保留 + alias 指向新名），
            # stars 最高也必须被候选圈选与状态计数同时排除——否则富化写入
            # 归一到新名行后旧名行永远 pending，队列清不零。
            cursor.execute("""INSERT INTO github_repo_candidates
                (repo_id,full_name,description,language,topics_json,stars,forks,watchers)
                VALUES ('canonical','acme/agent','Agent','Python','[\"rag\"]',600,2,3),
                       ('new','acme/new','New','Go','[]',550,1,1),
                       ('renamed_old','acme/old-name','Old','Rust','[]',900,9,9)""")
            cursor.execute("""INSERT INTO github_repo_aliases
                (alias_repo_id,canonical_repo_id,full_name) VALUES ('alias','canonical','old/agent'),
                ('renamed_old','canonical','acme/old-name')""")
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
        "unprocessable": 0, "unprocessable_projects": [],
        "by_category": [{"slug": "agent", "name": "Agent", "count": 1}],
    }
    assert [row["repo_id"] for row in github.get_github_projects_needing_enrichment(retry_failed=True)] == ["new"]


def test_pg16_readme_only_repos_enter_enrichment_and_not_found_stay_out_of_unprocessable(
    repositories,
) -> None:
    """description 空 + 成功 README 的仓库进入标准队列；404 下架仓库不进无法富化名单。"""
    database, github, _ = repositories
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""INSERT INTO github_repo_candidates
                (repo_id,full_name,description,language,topics_json,stars,forks,watchers,availability_status)
                VALUES
                ('readme_only','acme/readme-only','','Python','[]',800,1,1,'active'),
                ('readme_failed','acme/readme-failed','','Go','[]',700,1,1,'active'),
                ('both_empty','acme/both-empty','','Rust','[]',650,1,1,'active'),
                ('gone','QAI-brain/awesome-QAI-Papers-QDiffusion','','','[]',900,1,1,'not_found')""")
            cursor.execute("""INSERT INTO github_project_semantic_sources
                (repo_id,readme_text,readme_sha256,readme_status,updated_at)
                VALUES
                ('readme_only','Awesome QAI papers README body','h1','succeeded','now'),
                ('readme_failed','stale text','h2','failed','now'),
                ('gone','','','not_found','now')""")

    queue = {row["repo_id"] for row in github.get_github_projects_needing_enrichment(limit=100)}
    # README-only 首次可富化；failed/空 README 与 404 仓库都不是可富化输入
    assert "readme_only" in queue
    assert "readme_failed" not in queue
    assert "both_empty" not in queue
    assert "gone" not in queue

    status = github.get_github_project_enrichment_status(min_stars=500)
    unprocessable_ids = {row["repo_id"] for row in status["unprocessable_projects"]}
    # 404（QDiffusion 形态）与有有效 README 的都不进名单；仅真正双空的计入，
    # 且计数与详情列表一致
    assert "gone" not in unprocessable_ids
    assert "readme_only" not in unprocessable_ids
    assert "readme_failed" in unprocessable_ids
    assert "both_empty" in unprocessable_ids
    assert status["unprocessable"] == len(unprocessable_ids)


def test_pg16_readme_hash_change_triggers_refresh(repositories) -> None:
    """README 快照 hash 变化改变源指纹，refresh_changed 重新圈选已富化项目。"""
    database, github, _ = repositories
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""INSERT INTO github_repo_candidates
                (repo_id,full_name,description,language,topics_json,stars,forks,watchers)
                VALUES ('readme_fp','acme/readme-fp','','Python','[]',800,1,1)""")
            cursor.execute("""INSERT INTO github_project_semantic_sources
                (repo_id,readme_text,readme_sha256,readme_status,updated_at)
                VALUES ('readme_fp','README v1 body','hash-v1','succeeded','now')""")

    row = next(
        item
        for item in github.get_github_projects_needing_enrichment(limit=100)
        if item["repo_id"] == "readme_fp"
    )
    github.upsert_github_repo_enrichment({
        "repo_id": "readme_fp", "category_slug": "agent", "category_name": "Agent",
        "description_zh": "智能体", "description_en": "Agent",
        "tags": [], "source_fingerprint": row["source_fingerprint"],
        "prompt_version": "v1",
    })
    assert "readme_fp" not in {
        item["repo_id"]
        for item in github.get_github_projects_needing_enrichment(
            refresh_changed=True, prompt_version="v1", limit=100,
        )
    }

    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE github_project_semantic_sources "
                "SET readme_text='README v2 body', readme_sha256='hash-v2' "
                "WHERE repo_id='readme_fp'"
            )
    assert "readme_fp" in {
        item["repo_id"]
        for item in github.get_github_projects_needing_enrichment(
            refresh_changed=True, prompt_version="v1", limit=100,
        )
    }


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


def test_pg16_refresh_changed_uses_sql_fingerprint_equivalent_to_python(repositories) -> None:
    """refresh_changed 的 SQL 指纹下推与 Python 侧 _github_fingerprint 严格一致。"""
    database, github, _ = repositories
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""INSERT INTO github_repo_candidates
                (repo_id,full_name,description,language,topics_json,stars,forks,watchers)
                VALUES ('stable','acme/稳定','Agent 描述','Python','[\"rag\"]',900,2,3)""")

    # 模块共享 schema 内可能有前序用例的其他 repo，断言只锁定 stable 一行
    stable = next(
        row
        for row in github.get_github_projects_needing_enrichment(limit=50)
        if row["repo_id"] == "stable"
    )
    fingerprint = stable["source_fingerprint"]
    github.upsert_github_repo_enrichment({
        "repo_id": "stable", "category_slug": "agent", "category_name": "Agent",
        "description_zh": "智能体", "description_en": "Agent",
        "tags": ["RAG"], "source_fingerprint": fingerprint,
        "prompt_version": "v1",
    })

    # 指纹、双语字段与版本一致：SQL 下推必须排除该项目
    assert "stable" not in {
        row["repo_id"]
        for row in github.get_github_projects_needing_enrichment(
            refresh_changed=True, prompt_version="v1", limit=50,
        )
    }

    # prompt_version 变化触发重富化
    assert "stable" in {
        row["repo_id"]
        for row in github.get_github_projects_needing_enrichment(
            refresh_changed=True, prompt_version="v2", limit=50,
        )
    }

    # 内容变化（SQL 指纹随之变化）触发重富化
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE github_repo_candidates SET description='New 描述' "
                "WHERE repo_id='stable'"
            )
    assert "stable" in {
        row["repo_id"]
        for row in github.get_github_projects_needing_enrichment(
            refresh_changed=True, prompt_version="v1", limit=50,
        )
    }
