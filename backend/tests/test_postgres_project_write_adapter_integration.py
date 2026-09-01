from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterator

import pytest

from backend.tests.postgres_test_safety import postgres_test_sandbox

_TESTS_DIR = Path(__file__).resolve().parent
_IMPORT_CWD = Path.cwd()
os.chdir(_TESTS_DIR)
try:
    psycopg = pytest.importorskip("psycopg")
    pytest.importorskip("psycopg_pool")

    from backend.app.repositories.postgres_project_write_repository import (
        PostgresProjectWriteRepository,
    )
finally:
    os.chdir(_IMPORT_CWD)


@pytest.fixture(scope="module")
def write_repository() -> Iterator[tuple[Any, PostgresProjectWriteRepository]]:
    with postgres_test_sandbox() as sandbox:
        database = sandbox.database
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
                        subcategory_name, description_zh, tags_json, tags_zh_json, tags_en_json,
                        source_fingerprint, prompt_version, status)
                   VALUES ('canonical-1', 'agent', 'Agent', 'workflow', 'Workflow',
                           '项目', '[\"MCP\", \"AI 工具\"]', '[\"MCP\", \"AI 工具\"]', '[\"MCP\", \"AI tools\"]', repeat('a', 64), 'v1', 'succeeded');
                   INSERT INTO tool_websites
                       (id, canonical_url, normalized_url_hash, domain, title,
                        source_fingerprint, visibility, added_by_user_id)
                   VALUES (11, 'https://tool.example/path', repeat('b', 64),
                           'tool.example', 'Tool', repeat('c', 64), 'private', 7);
                   INSERT INTO tool_website_enrichments
                       (website_id, category_slug, category_name, subcategory_slug,
                        subcategory_name, description_zh, tags_json, tags_zh_json, tags_en_json,
                        source_fingerprint, prompt_version, status)
                   VALUES (11, 'productivity', 'Productivity', 'notes', 'Notes',
                           '工具', '[\"base\"]', '[\"基础\"]', '[\"Base\"]', repeat('d', 64), 'v1', 'succeeded')"""
            )
        yield database, PostgresProjectWriteRepository(database)


def test_real_postgres_canonical_favorite_and_recommendation(
    write_repository: tuple[Any, PostgresProjectWriteRepository],
) -> None:
    _, repository = write_repository

    favorite = repository.add_project_favorite(user_id=7, source="github", repo_id="legacy-1")
    recommendation = repository.recommend_github_project(full_name="acme/project", recommended_by_user_id=7)

    assert favorite["repo_id"] == "canonical-1"
    assert favorite["favorited_at"]
    assert recommendation["repo_id"] == "canonical-1"
    assert recommendation["is_recommended"] is True
    assert repository.get_user_project_tags(user_id=7) == {
        "items": [
            {
                "label": "MCP",
                "value": "MCP",
                "label_zh": "MCP",
                "label_en": "MCP",
                "count": 1,
                "tags_origin": "system",
            }
        ],
        "total": 1,
        "source": "github",
    }
    assert repository.unrecommend_github_project(repo_id="legacy-1")["removed"] is True
    assert repository.remove_project_favorite(user_id=7, source="github", repo_id="legacy-1") is True


def test_real_postgres_tool_collection_override_and_atomic_unlink(
    write_repository: tuple[Any, PostgresProjectWriteRepository],
) -> None:
    database, repository = write_repository

    linked = repository.link_user_tool_website(user_id=7, website_id=11, added_via="manual")
    favorite = repository.add_project_favorite(user_id=7, source="website", website_id=11)
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
    collection = repository.list_user_project_collection(user_id=7, source="website", min_stars=0, enriched_only=True)
    assert collection["total"] == 1
    assert collection["items"][0]["category_slug"] == "custom"
    assert repository.get_user_project_tags(user_id=7, source="website") == {
        "items": [
            {
                "label": "mine",
                "value": "mine",
                "label_zh": "mine",
                "label_en": "mine",
                "count": 1,
                "tags_origin": "user",
            }
        ],
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
