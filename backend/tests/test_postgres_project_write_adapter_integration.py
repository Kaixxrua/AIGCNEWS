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
    from backend.app.repositories.postgres_project_write_repository import (
        PostgresProjectWriteRepository,
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
def write_repository() -> Iterator[tuple[Any, PostgresProjectWriteRepository]]:
    dsn = _test_dsn()
    schema = f"project_write_it_{uuid.uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public")
        admin.execute(f'CREATE SCHEMA "{schema}"')
    scoped_dsn = make_conninfo(dsn, options=f"-c search_path={schema}")
    database = PostgresDatabaseLifecycle(
        lambda: ConnectionPool(
            conninfo=scoped_dsn,
            min_size=1,
            max_size=2,
            timeout=10,
            kwargs={"autocommit": False, "row_factory": psycopg.rows.dict_row},
            open=False,
        )
    )
    try:
        PostgresMigrationRunner(database).apply()
        with database.transaction() as connection:
            connection.execute(
                """INSERT INTO users (id, username, hashed_password) VALUES
                       (7, 'collector', 'hash'), (8, 'other', 'hash');
                   INSERT INTO github_repo_candidates
                       (repo_id, full_name, title, url, stars, forks, last_seen_at)
                   VALUES ('canonical-1', 'Acme/Project', 'Project',
                           'https://github.com/Acme/Project', 900, 10, '2026-01-01');
                   INSERT INTO github_repo_aliases
                       (alias_repo_id, canonical_repo_id, full_name)
                   VALUES ('legacy-1', 'canonical-1', 'old/Project');
                   INSERT INTO github_repo_enrichments
                       (repo_id, category_slug, category_name, subcategory_slug,
                        subcategory_name, description_zh, tags_json,
                        source_fingerprint, prompt_version, status)
                   VALUES ('canonical-1', 'agent', 'Agent', 'workflow', 'Workflow',
                           '项目', '[\"MCP\", \"AI 工具\"]', repeat('a', 64), 'v1', 'succeeded');
                   INSERT INTO tool_websites
                       (id, canonical_url, normalized_url_hash, domain, title,
                        source_fingerprint, visibility, added_by_user_id)
                   VALUES (11, 'https://tool.example/path', repeat('b', 64),
                           'tool.example', 'Tool', repeat('c', 64), 'private', 7);
                   INSERT INTO tool_website_enrichments
                       (website_id, category_slug, category_name, subcategory_slug,
                        subcategory_name, description_zh, tags_json,
                        source_fingerprint, prompt_version, status)
                   VALUES (11, 'productivity', 'Productivity', 'notes', 'Notes',
                           '工具', '[\"base\"]', repeat('d', 64), 'v1', 'succeeded')"""
            )
        yield database, PostgresProjectWriteRepository(database)
    finally:
        database.close()
        with psycopg.connect(dsn, autocommit=True) as admin:
            admin.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')


def test_real_postgres_canonical_favorite_and_recommendation(
    write_repository: tuple[Any, PostgresProjectWriteRepository],
) -> None:
    _, repository = write_repository

    favorite = repository.add_project_favorite(
        user_id=7, source="github", repo_id="legacy-1"
    )
    recommendation = repository.recommend_github_project(
        full_name="acme/project", recommended_by_user_id=7
    )

    assert favorite["repo_id"] == "canonical-1"
    assert favorite["favorited_at"]
    assert recommendation["repo_id"] == "canonical-1"
    assert recommendation["is_recommended"] is True
    assert repository.get_user_project_tags(user_id=7) == {
        "items": [{"label": "MCP", "count": 1}],
        "total": 1,
        "source": "github",
    }
    assert repository.unrecommend_github_project(repo_id="legacy-1")["removed"] is True
    assert repository.remove_project_favorite(
        user_id=7, source="github", repo_id="legacy-1"
    ) is True


def test_real_postgres_tool_collection_override_and_atomic_unlink(
    write_repository: tuple[Any, PostgresProjectWriteRepository],
) -> None:
    database, repository = write_repository

    linked = repository.link_user_tool_website(
        user_id=7, website_id=11, added_via="manual"
    )
    favorite = repository.add_project_favorite(
        user_id=7, source="website", website_id=11
    )
    item = repository.upsert_user_tool_website_override(
        {
            "user_id": 7,
            "website_id": 11,
            "title": "My Tool",
            "category_slug": "custom",
            "category_name": "Custom",
            "tags": ["mine", "网页收藏"],
        }
    )

    assert linked["user_added"] is True
    assert favorite["website_id"] == 11
    assert item["title"] == "My Tool"
    assert item["is_favorited"] is True
    collection = repository.list_user_project_collection(
        user_id=7, source="website", min_stars=0, enriched_only=True
    )
    assert collection["total"] == 1
    assert collection["items"][0]["category_slug"] == "custom"
    assert repository.get_user_project_tags(user_id=7, source="website") == {
        "items": [{"label": "mine", "count": 1}],
        "total": 1,
        "source": "website",
    }

    assert repository.unlink_user_tool_website(user_id=7, website_id=11) is True
    with database.transaction() as connection:
        rows = connection.execute(
            """SELECT
                   (SELECT COUNT(*) FROM user_tool_websites WHERE user_id=7 AND website_id=11) links,
                   (SELECT COUNT(*) FROM user_tool_website_overrides WHERE user_id=7 AND website_id=11) overrides,
                   (SELECT COUNT(*) FROM project_favorites WHERE user_id=7
                       AND project_source='website' AND project_id='11') favorites"""
        ).fetchone()
    assert rows == {"links": 0, "overrides": 0, "favorites": 0}


def test_real_postgres_tool_favorite_requires_user_access(
    write_repository: tuple[Any, PostgresProjectWriteRepository],
) -> None:
    _, repository = write_repository

    with pytest.raises(LookupError, match="不可收藏"):
        repository.add_project_favorite(user_id=8, source="website", website_id=11)
