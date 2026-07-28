from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

from backend.app.repositories.postgres_project_enrichment_repository import (
    PostgresGitHubProjectEnrichmentRepository,
    PostgresToolWebsiteEnrichmentRepository,
)
from backend.app.repositories.project_write_repository import (
    GitHubProjectEnrichmentRepository,
    ToolWebsiteEnrichmentRepository,
)


class FakeDatabase:
    def __init__(self, cursor: MagicMock) -> None:
        self.cursor = cursor
        self.connection = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = cursor
        self.connection.cursor.return_value = context
        self.transaction_count = 0

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        yield self.connection


def test_postgres_enrichment_adapters_expose_protocols_and_provider_reader() -> None:
    database = FakeDatabase(MagicMock())
    github: GitHubProjectEnrichmentRepository = PostgresGitHubProjectEnrichmentRepository(database)  # type: ignore[arg-type]
    websites: ToolWebsiteEnrichmentRepository = PostgresToolWebsiteEnrichmentRepository(database)  # type: ignore[arg-type]

    assert github.runtime_provider_settings is github.runtime_provider_settings
    assert websites.runtime_provider_settings is websites.runtime_provider_settings
    assert callable(github.get_github_projects_needing_enrichment)
    assert callable(websites.upsert_tool_website)


def test_github_candidate_selection_preserves_fingerprint_and_refresh_semantics() -> None:
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {
            "repo_id": "1", "full_name": "acme/agent", "description": "Agent",
            "language": "Python", "topics_json": '["rag"]', "stars": 800,
            "existing_status": "succeeded", "existing_prompt_version": "v1",
            "existing_source_fingerprint": "stale",
        },
        {
            "repo_id": "2", "full_name": "acme/new", "description": "New",
            "language": "Go", "topics_json": "[]", "stars": 700,
            "existing_status": None, "existing_prompt_version": None,
            "existing_source_fingerprint": None,
        },
    ]
    repository = PostgresGitHubProjectEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]

    normal = repository.get_github_projects_needing_enrichment(refresh_changed=False)
    refreshed = repository.get_github_projects_needing_enrichment(refresh_changed=True)

    assert [row["repo_id"] for row in normal] == ["2"]
    assert [row["repo_id"] for row in refreshed] == ["1", "2"]
    assert refreshed[0]["topics"] == ["rag"]
    assert len(refreshed[0]["source_fingerprint"]) == 64
    assert "DISTINCT ON (repo_id)" in cursor.execute.call_args_list[0].args[0]


def test_failure_writes_defaults_truncates_error_and_resolves_alias() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = {"canonical_repo_id": "canonical"}
    repository = PostgresGitHubProjectEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]

    repository.mark_github_repo_enrichment_failed(
        "alias", source_fingerprint="f" * 64, prompt_version="v2", error_msg="x" * 2100
    )

    _, upsert = cursor.execute.call_args_list
    params = upsert.args[1]
    assert params["repo_id"] == "canonical"
    assert params["status"] == "failed"
    assert params["subcategory_slug"] == "other_uncategorized"
    assert len(params["error_msg"]) == 2000
    assert "ON CONFLICT (repo_id) DO UPDATE" in upsert.args[0]


def test_website_upsert_preserves_canonical_merge_policy() -> None:
    cursor = MagicMock()
    cursor.fetchone.return_value = {"id": 4, "normalized_url_hash": "hash"}
    repository = PostgresToolWebsiteEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]

    result = repository.upsert_tool_website({
        "canonical_url": "https://tool.test/docs", "normalized_url_hash": "hash",
        "domain": "tool.test", "source_fingerprint": "f" * 64, "visibility": "INVALID",
    })

    sql, params = cursor.execute.call_args.args
    assert result["id"] == 4
    assert params["visibility"] == "public"
    assert params["raw_metadata_json"] == "{}"
    assert "COALESCE(NULLIF(EXCLUDED.title,''),tool_websites.title)" in sql
    assert "tool_websites.visibility='public' OR EXCLUDED.visibility='public'" in sql


def test_website_failure_uses_same_enrichment_upsert_defaults() -> None:
    cursor = MagicMock()
    repository = PostgresToolWebsiteEnrichmentRepository(FakeDatabase(cursor))  # type: ignore[arg-type]

    repository.mark_tool_website_enrichment_failed(
        9, source_fingerprint="f" * 64, prompt_version="v1", error_msg="bad"
    )

    params = cursor.execute.call_args.args[1]
    assert params["website_id"] == 9
    assert params["status"] == "failed"
    assert params["category_slug"] == "other"
    assert params["tags_json"] == "[]"
