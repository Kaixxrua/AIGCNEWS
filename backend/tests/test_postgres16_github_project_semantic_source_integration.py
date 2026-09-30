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

    from backend.app.core.postgres_database import PostgresDatabaseLifecycle
    from backend.app.repositories.postgres_github_project_semantic_repository import (
        PostgresGitHubProjectSemanticSourceRepository,
    )
finally:
    os.chdir(_IMPORT_CWD)


@pytest.fixture(scope="module")
def semantic_repository() -> Iterator[tuple[Any, PostgresDatabaseLifecycle]]:
    with postgres_test_sandbox() as sandbox:
        database = sandbox.database
        with database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO github_repo_candidates
                    (repo_id, full_name, title, stars, forks, topics_json, pushed_at)
                VALUES
                    ('acme/alias', 'acme/alias', 'Alias', 2000, 1, '[]', '2026-07-27'),
                    ('acme/alpha', 'acme/alpha', 'Alpha', 1000, 10, '["rag"]', '2026-07-28'),
                    ('acme/beta', 'acme/beta', 'Beta', 900, 9, '["agent"]', '2026-07-28'),
                    ('acme/low', 'acme/low', 'Low', 499, 2, '[]', '2026-07-28');
                INSERT INTO github_repo_aliases
                    (alias_repo_id, canonical_repo_id, full_name)
                VALUES ('acme/alias', 'acme/alpha', 'acme/alias');
                INSERT INTO github_repo_enrichments
                    (repo_id, category_slug, category_name, description_zh,
                     tags_json, source_fingerprint, prompt_version, status)
                VALUES
                    ('acme/alias', 'other', 'Other', 'alias', '[]', repeat('a',64), 'v1', 'succeeded'),
                    ('acme/alpha', 'rag', 'RAG', 'alpha', '["local"]', repeat('b',64), 'v1', 'succeeded'),
                    ('acme/beta', 'agent', 'Agent', 'beta', '["workflow"]', repeat('c',64), 'v1', 'succeeded'),
                    ('acme/low', 'other', 'Other', 'low', '[]', repeat('d',64), 'v1', 'succeeded');
                """
            )
        yield PostgresGitHubProjectSemanticSourceRepository(database), database


def test_postgres16_sync_upsert_retry_transitions_and_status(
    semantic_repository: tuple[Any, PostgresDatabaseLifecycle],
) -> None:
    repository, database = semantic_repository

    initial = repository.list_github_projects_for_semantic_sync(min_stars=500)
    assert [row["repo_id"] for row in initial] == ["acme/alpha", "acme/beta"]
    assert initial[0]["topics"] == ["rag"]
    assert initial[0]["tags"] == ["local"]

    repository.upsert_github_project_semantic_source(
        {
            "repo_id": "acme/alias",
            "readme_status": "failed",
            "readme_retry_count": 2,
            "readme_next_retry_at": "2026-07-29T00:00:00Z",
            "source_fingerprint": "source-alpha",
            "indexed_fingerprint": "old-alpha",
            "index_status": "failed",
            "index_error": "retry me",
            "index_retry_count": 3,
            "index_next_retry_at": "2026-07-30T00:00:00Z",
            "chunk_count": 4,
        }
    )
    with database.transaction() as connection:
        state = connection.execute(
            "SELECT * FROM github_project_semantic_sources WHERE repo_id='acme/alpha'"
        ).fetchone()
    assert state["readme_retry_count"] == 2
    assert state["readme_next_retry_at"] == "2026-07-29T00:00:00Z"
    assert state["index_retry_count"] == 3
    assert state["index_next_retry_at"] == "2026-07-30T00:00:00Z"

    no_failed_retry = repository.list_github_projects_for_semantic_sync(min_stars=500, retry_failed=False)
    assert [row["repo_id"] for row in no_failed_retry] == ["acme/alpha", "acme/beta"]

    repository.upsert_github_project_semantic_source(
        {
            "repo_id": "acme/alpha",
            "readme_status": "succeeded",
            "source_fingerprint": "source-alpha",
            "indexed_fingerprint": "source-alpha",
            "index_version": "v1",
            "index_status": "succeeded",
            "chunk_count": 8,
            "indexed_at": "2026-07-28T12:00:00Z",
        }
    )
    repository.upsert_github_project_semantic_source(
        {
            "repo_id": "acme/beta",
            "readme_status": "failed",
            "index_status": "failed",
            "index_retry_count": 1,
        }
    )

    status = repository.get_github_project_semantic_status(min_stars=500)
    assert status == {
        "eligible": 2,
        "indexed": 1,
        "failed": 1,
        "pending": 0,
        "readme_succeeded": 1,
        "chunk_count": 8,
        "last_indexed_at": "2026-07-28T12:00:00Z",
    }


def test_postgres16_ledger_reconcile_requeues_only_succeeded_rows(
    semantic_repository: tuple[Any, PostgresDatabaseLifecycle],
) -> None:
    repository, database = semantic_repository
    repository.upsert_github_project_semantic_source(
        {
            "repo_id": "acme/alpha",
            "readme_text": "alpha readme",
            "readme_sha256": "readme-alpha",
            "readme_status": "succeeded",
            "source_fingerprint": "source-alpha",
            "indexed_fingerprint": "source-alpha",
            "index_version": "v1",
            "index_status": "succeeded",
            "chunk_count": 8,
            "indexed_at": "2026-07-28T12:00:00Z",
        }
    )
    repository.upsert_github_project_semantic_source(
        {"repo_id": "acme/beta", "index_status": "failed", "index_retry_count": 1}
    )

    assert repository.list_indexed_github_project_ids() == ["acme/alpha"]
    requeued = repository.requeue_github_project_semantic_index(
        ["acme/alpha", "acme/beta", ""], reason="vectors missing", updated_at="2026-09-30T00:00:00Z"
    )
    assert requeued == 1

    with database.transaction() as connection:
        alpha = connection.execute(
            "SELECT * FROM github_project_semantic_sources WHERE repo_id='acme/alpha'"
        ).fetchone()
        beta = connection.execute(
            "SELECT * FROM github_project_semantic_sources WHERE repo_id='acme/beta'"
        ).fetchone()
    # indexed_fingerprint 是 CHAR(64)：空串按 bpchar 补齐为空格，比较语义等同空串。
    assert (alpha["index_status"], alpha["indexed_fingerprint"].strip(), alpha["chunk_count"]) == ("pending", "", 0)
    assert alpha["index_error"] == "vectors missing"
    assert (alpha["readme_text"], alpha["readme_sha256"].strip(), alpha["source_fingerprint"].strip()) == (
        "alpha readme",
        "readme-alpha",
        "source-alpha",
    )
    assert beta["index_status"] == "failed"
    assert repository.list_indexed_github_project_ids() == []
    selected = repository.list_github_projects_for_semantic_sync(min_stars=500)
    assert "acme/alpha" in [row["repo_id"] for row in selected]
