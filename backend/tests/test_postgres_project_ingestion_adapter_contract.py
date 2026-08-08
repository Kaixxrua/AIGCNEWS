from __future__ import annotations

import inspect

from backend.app.repositories.postgres_project_ingestion_repository import (
    PostgresGitHubProjectIngestionRepository,
)
from backend.app.repositories.project_write_repository import (
    GitHubProjectIngestionRepository,
)


def test_postgres_ingestion_adapter_covers_protocol_operations() -> None:
    expected = {
        name
        for name, value in GitHubProjectIngestionRepository.__dict__.items()
        if inspect.isfunction(value) and not name.startswith("__")
    }

    assert expected == {
        "upsert_github_repo_candidate",
        "get_github_repo_source_channels",
        "mark_github_repo_available",
        "record_github_repo_not_found",
        "ensure_github_repo_candidate",
        "insert_github_repo_snapshot",
        "upsert_github_repo_metric_observations",
        "upsert_github_trending_hit",
        "get_github_hot_repos",
        "get_github_snapshot_count",
        "list_github_project_metric_targets",
        "get_github_metric_refresh_status",
        "get_github_daily_metric_inputs",
        "upsert_github_daily_metrics",
    }
    assert expected.issubset(PostgresGitHubProjectIngestionRepository.__dict__)


def test_postgres_ingestion_adapter_is_structurally_assignable() -> None:
    repository = PostgresGitHubProjectIngestionRepository.__new__(
        PostgresGitHubProjectIngestionRepository
    )

    ingestion: GitHubProjectIngestionRepository = repository

    assert ingestion is repository
