from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.app.repositories.application_repository_context import (
    configure_application_repositories,
)
from backend.app.repositories.project_write_repository import (
    GitHubProjectIngestionRepository,
)
from backend.app.services.ingestion import github_hot_service
from backend.app.services.ingestion.source_github import GitHubRepoMetricsResult


def test_hot_rank_uses_explicit_repository() -> None:
    repository = MagicMock(spec=GitHubProjectIngestionRepository)
    repository.get_github_hot_repos.return_value = [{"repo_id": "repo-1"}]
    repository.get_github_snapshot_count.return_value = 8

    result = github_hot_service.get_github_hot_rank(
        "weekly",
        limit=4,
        db=repository,
    )

    assert result == {
        "period": "weekly",
        "window_days": 7,
        "items": [{"repo_id": "repo-1"}],
        "total": 1,
        "snapshot_count": 8,
    }
    repository.get_github_hot_repos.assert_called_once_with("weekly", limit=4)


def test_hot_rank_uses_configured_application_repository() -> None:
    repository = MagicMock(spec=GitHubProjectIngestionRepository)
    repository.get_github_hot_repos.return_value = []
    repository.get_github_snapshot_count.return_value = 0
    configure_application_repositories(
        SimpleNamespace(github_ingestion=repository)
    )
    try:
        result = github_hot_service.get_github_hot_rank()
    finally:
        configure_application_repositories(None)

    assert result["total"] == 0
    repository.get_github_hot_repos.assert_called_once_with("daily", limit=10)


def test_refresh_candidates_uses_explicit_repository(monkeypatch) -> None:
    repository = MagicMock(spec=GitHubProjectIngestionRepository)
    repository.upsert_github_repo_candidate.return_value = "repo-1"
    repository.upsert_github_trending_hit.return_value = "repo-1"
    monkeypatch.setattr(
        github_hot_service,
        "fetch_github_trending_repos",
        lambda *, period, limit: (
            [{"full_name": "acme/project", "stars": 700}]
            if period == "daily"
            else []
        ),
    )
    monkeypatch.setattr(
        github_hot_service,
        "fetch_github_candidate_repos",
        lambda *, limit: [],
    )
    monkeypatch.setattr(
        github_hot_service,
        "fetch_github_repo_metrics_batch",
        lambda names: [],
    )

    result = github_hot_service.refresh_github_hot_candidates(
        20,
        observed_date="2026-07-28",
        db=repository,
    )

    assert result["repos"] == 1
    assert result["snapshots"] == 1
    repository.upsert_github_repo_candidate.assert_called_once()
    assert repository.insert_github_repo_snapshot.call_count == 2
    repository.upsert_github_trending_hit.assert_called_once()


def test_search_only_candidate_keeps_community_metrics_incomplete(monkeypatch) -> None:
    repository = MagicMock(spec=GitHubProjectIngestionRepository)
    monkeypatch.setattr(
        github_hot_service,
        "fetch_github_trending_repos",
        lambda *, period, limit: [],
    )
    monkeypatch.setattr(
        github_hot_service,
        "fetch_github_repo_metrics_batch",
        lambda names: [],
    )
    monkeypatch.setattr(
        github_hot_service,
        "fetch_github_candidate_repos",
        lambda *, limit: [
            {
                "full_name": "acme/project",
                "stars": 700,
                "watchers": 0,
                "community_metrics_complete": False,
            }
        ],
    )

    github_hot_service.refresh_github_hot_candidates(
        20,
        observed_date="2026-07-28",
        db=repository,
    )

    candidate = repository.upsert_github_repo_candidate.call_args.args[0]
    snapshot = repository.insert_github_repo_snapshot.call_args.args[0]
    assert candidate["watchers"] == 0
    assert candidate["community_metrics_complete"] is False
    assert snapshot["watchers"] == 0
    assert snapshot["community_metrics_complete"] == 0


def test_search_merge_preserves_authoritative_subscriber_count(monkeypatch) -> None:
    repository = MagicMock(spec=GitHubProjectIngestionRepository)
    monkeypatch.setattr(
        github_hot_service,
        "fetch_github_trending_repos",
        lambda *, period, limit: (
            [{"full_name": "acme/project", "stars": 700}]
            if period == "daily"
            else []
        ),
    )
    monkeypatch.setattr(
        github_hot_service,
        "fetch_github_repo_metrics_batch",
        lambda names: [
            GitHubRepoMetricsResult(
                "acme/project",
                "succeeded",
                metrics={
                    "full_name": "acme/project",
                    "stars": 710,
                    "watchers": 12,
                    "community_metrics_complete": True,
                },
            )
        ],
    )
    monkeypatch.setattr(
        github_hot_service,
        "fetch_github_candidate_repos",
        lambda *, limit: [
            {
                "full_name": "acme/project",
                "stars": 720,
                "watchers": 0,
                "community_metrics_complete": False,
            }
        ],
    )

    github_hot_service.refresh_github_hot_candidates(
        20,
        observed_date="2026-07-28",
        db=repository,
    )

    candidate = repository.upsert_github_repo_candidate.call_args.args[0]
    first_snapshot = repository.insert_github_repo_snapshot.call_args_list[0].args[0]
    assert candidate["stars"] == 720
    assert candidate["watchers"] == 12
    assert candidate["community_metrics_complete"] is True
    assert first_snapshot["watchers"] == 12
    assert first_snapshot["community_metrics_complete"] == 1
