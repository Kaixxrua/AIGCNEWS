from __future__ import annotations

from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.repositories.project_write_repository import (
    GitHubProjectEnrichmentRepository,
    GitHubProjectIngestionRepository,
    GitHubProjectRecommendationRepository,
    GitHubProjectSemanticSourceRepository,
    ToolWebsiteEnrichmentRepository,
    UserProjectCollectionRepository,
)


def test_mysql_repository_structurally_satisfies_project_write_protocols() -> None:
    repository = MySQLRepository.__new__(MySQLRepository)

    ingestion: GitHubProjectIngestionRepository = repository
    enrichment: GitHubProjectEnrichmentRepository = repository
    recommendation: GitHubProjectRecommendationRepository = repository
    semantic: GitHubProjectSemanticSourceRepository = repository
    websites: ToolWebsiteEnrichmentRepository = repository
    collections: UserProjectCollectionRepository = repository

    assert ingestion is repository
    assert enrichment is repository
    assert recommendation is repository
    assert semantic is repository
    assert websites is repository
    assert collections is repository


def test_project_write_protocols_cover_all_runtime_operations() -> None:
    expected = {
        GitHubProjectIngestionRepository: {
            "upsert_github_repo_candidate",
            "mark_github_repo_available",
            "record_github_repo_not_found",
            "ensure_github_repo_candidate",
            "insert_github_repo_snapshot",
            "upsert_github_trending_hit",
            "get_github_hot_repos",
            "get_github_snapshot_count",
            "list_github_project_metric_targets",
            "get_github_metric_refresh_status",
            "get_github_daily_metric_inputs",
            "upsert_github_daily_metrics",
        },
        GitHubProjectEnrichmentRepository: {
            "runtime_provider_settings",
            "get_github_projects_needing_enrichment",
            "upsert_github_repo_enrichment",
            "mark_github_repo_enrichment_failed",
            "get_github_project_enrichment_status",
        },
        ToolWebsiteEnrichmentRepository: {
            "runtime_provider_settings",
            "get_tool_website_by_hash",
            "upsert_tool_website",
            "get_tool_website_enrichment",
            "get_tool_website_item",
            "upsert_tool_website_enrichment",
            "mark_tool_website_enrichment_failed",
        },
        UserProjectCollectionRepository: {
            "add_project_favorite",
            "remove_project_favorite",
            "link_user_tool_website",
            "unlink_user_tool_website",
            "get_tool_website_item_for_user",
            "upsert_user_tool_website_override",
            "list_user_project_collection",
            "get_user_project_categories",
            "get_user_project_tags",
        },
        GitHubProjectRecommendationRepository: {
            "recommend_github_project",
            "unrecommend_github_project",
        },
        GitHubProjectSemanticSourceRepository: {
            "list_github_projects_for_semantic_sync",
            "upsert_github_project_semantic_source",
            "get_github_project_semantic_status",
        },
    }

    for protocol, methods in expected.items():
        assert methods.issubset(protocol.__dict__)
        assert methods.issubset(MySQLRepository.__dict__)
