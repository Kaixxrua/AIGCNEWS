from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from backend.app.repositories.postgres_github_project_semantic_repository import (
    PostgresGitHubProjectSemanticSourceRepository,
)
from backend.app.repositories.project_write_repository import (
    GitHubProjectSemanticSourceRepository,
)


class FakeDatabase:
    def __init__(self, cursor: MagicMock) -> None:
        self.cursor = cursor
        self.connection = MagicMock()
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        self.connection.cursor.return_value = cursor_context
        self.transaction_count = 0

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        yield self.connection


def _repository() -> tuple[PostgresGitHubProjectSemanticSourceRepository, FakeDatabase, MagicMock]:
    cursor = MagicMock()
    database = FakeDatabase(cursor)
    return PostgresGitHubProjectSemanticSourceRepository(database), database, cursor


def test_adapter_structurally_satisfies_semantic_source_contract() -> None:
    repository, _, _ = _repository()
    contract: GitHubProjectSemanticSourceRepository = repository

    assert callable(contract.list_github_projects_for_semantic_sync)
    assert callable(contract.upsert_github_project_semantic_source)
    assert callable(contract.mark_github_project_semantic_snapshot_current)
    assert callable(contract.get_github_project_semantic_status)


def test_mark_snapshot_current_only_touches_watermark_columns() -> None:
    repository, database, cursor = _repository()

    repository.mark_github_project_semantic_snapshot_current(
        "owner/repo", repo_pushed_at="2026-08-01", checked_at="2026-08-17T00:00:00+00:00"
    )

    sql, params = cursor.execute.call_args.args
    assert sql.lstrip().startswith("UPDATE github_project_semantic_sources")
    assert "readme_repo_pushed_at" in sql
    assert "readme_checked_at" in sql
    assert "index_status" not in sql
    assert params == ("2026-08-01", "2026-08-17T00:00:00+00:00", "2026-08-17T00:00:00+00:00", "owner/repo")
    assert database.transaction_count == 1


def test_sync_query_preserves_filters_order_retry_policy_and_normalization() -> None:
    repository, database, cursor = _repository()
    cursor.fetchall.return_value = [{
        "repo_id": "owner/repo",
        "topics_json": '["rag"]',
        "tags_json": '["agent"]',
        "stars": 900,
        "forks": 12,
    }]

    with patch(
        "backend.app.repositories.postgres_github_project_semantic_repository.settings.project_semantic_index_version",
        "semantic-v9",
    ):
        rows = repository.list_github_projects_for_semantic_sync(
            limit=5000, min_stars=700, after_repo_id="owner/alpha", retry_failed=False
        )

    sql, params = cursor.execute.call_args.args
    assert "ge.status = 'succeeded'" in sql
    assert "ga.alias_repo_id = c.repo_id" in sql
    assert "ga.canonical_repo_id <> c.repo_id" in sql
    assert 'ORDER BY c.repo_id COLLATE "C" ASC' in sql
    assert "ss.readme_repo_pushed_at" in sql
    assert params == (700, "owner/alpha", ["pending"], "semantic-v9", 1000)
    assert rows[0]["topics"] == ["rag"]
    assert rows[0]["tags"] == ["agent"]
    assert rows[0]["stars"] == 900
    assert database.transaction_count == 1


def test_upsert_resolves_alias_and_replaces_all_state_with_mysql_defaults() -> None:
    repository, _, cursor = _repository()
    cursor.fetchone.return_value = {"canonical_repo_id": "owner/canonical"}

    repository.upsert_github_project_semantic_source({
        "repo_id": "owner/old-name",
        "readme_status": "failed",
        "readme_retry_count": 3,
        "readme_next_retry_at": "2026-07-29T00:00:00Z",
        "index_status": "failed",
        "index_error": "embedding failed",
        "index_retry_count": 4,
        "index_next_retry_at": "2026-07-30T00:00:00Z",
    })

    resolve_call, upsert_call = cursor.execute.call_args_list
    assert resolve_call.args[1] == ("owner/old-name",)
    sql, params = upsert_call.args
    assert "ON CONFLICT (repo_id) DO UPDATE" in sql
    assert "readme_retry_count = EXCLUDED.readme_retry_count" in sql
    assert "index_next_retry_at = EXCLUDED.index_next_retry_at" in sql
    assert params[0] == "owner/canonical"
    assert params[1:5] == (None, "", "", "failed")
    assert params[18] == "failed"
    assert 3 in params
    assert 4 in params


def test_status_aggregation_preserves_pending_derivation() -> None:
    repository, _, cursor = _repository()
    cursor.fetchone.return_value = {
        "eligible": 9,
        "indexed": 5,
        "failed": 2,
        "readme_succeeded": 6,
        "chunk_count": 21,
        "last_indexed_at": "2026-07-28T00:00:00Z",
    }

    status = repository.get_github_project_semantic_status(min_stars=750)

    sql, params = cursor.execute.call_args.args
    assert "COUNT(*) FILTER" in sql
    assert "ga.alias_repo_id = c.repo_id" in sql
    assert params == (750,)
    assert status == {
        "eligible": 9,
        "indexed": 5,
        "failed": 2,
        "pending": 2,
        "readme_succeeded": 6,
        "chunk_count": 21,
        "last_indexed_at": "2026-07-28T00:00:00Z",
    }
