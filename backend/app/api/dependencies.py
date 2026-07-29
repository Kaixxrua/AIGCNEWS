from __future__ import annotations

from fastapi import Depends, Request

from backend.app.repositories.application_repository_factory import (
    ApplicationRepositories,
)
from backend.app.repositories.briefing_repository import (
    BriefingContentRepository,
    BriefingSubscriptionRepository,
)
from backend.app.repositories.conversation_repository import ConversationRepository
from backend.app.repositories.document_repository import DocumentRepository, PapersReader
from backend.app.repositories.evaluation_repository import EvaluationRepository
from backend.app.repositories.mcp_access_token_repository import McpAccessTokenRepository
from backend.app.repositories.mcp_server_repository import McpServerConfigRepository
from backend.app.repositories.project_write_repository import (
    GitHubProjectEnrichmentRepository,
    GitHubProjectIngestionRepository,
    GitHubProjectRecommendationRepository,
    GitHubProjectSemanticSourceRepository,
    ToolWebsiteEnrichmentRepository,
    UserProjectCollectionRepository,
)
from backend.app.repositories.rank_snapshot_repository import RankSnapshotRepository
from backend.app.repositories.runtime_provider_repository import (
    RuntimeProviderSettingRepository,
)
from backend.app.repositories.task_repository import (
    IngestionTaskAdminRepository,
    IngestionTaskWriter,
    LatestTaskReader,
    MonitorTaskRepository,
    RecentTaskReader,
)
from backend.app.repositories.user_account_repository import UserAccountRepository
from backend.app.services.papers.pdf_relay import HttpxPdfRelay


class ApplicationIngestionTaskRepository(
    IngestionTaskWriter,
    LatestTaskReader,
    RecentTaskReader,
    MonitorTaskRepository,
    IngestionTaskAdminRepository,
):
    pass


def get_application_repositories(request: Request) -> ApplicationRepositories:
    repositories = getattr(request.app.state, "application_repositories", None)
    if repositories is None:
        raise RuntimeError("Application repositories are not configured")
    return repositories


def get_ingestion_task_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> ApplicationIngestionTaskRepository:
    return repositories.ingestion_tasks


def get_briefing_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> BriefingContentRepository:
    return repositories.briefings


def get_briefing_subscription_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> BriefingSubscriptionRepository:
    return repositories.briefing_subscriptions


def get_evaluation_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> EvaluationRepository:
    return repositories.evaluations


def get_mcp_server_config_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> McpServerConfigRepository:
    return repositories.mcp_server_configs


def get_mcp_access_token_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> McpAccessTokenRepository:
    return repositories.mcp_access_tokens


def get_user_account_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> UserAccountRepository:
    return repositories.users


def get_runtime_provider_setting_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> RuntimeProviderSettingRepository:
    return repositories.runtime_provider_settings


def get_conversation_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> ConversationRepository:
    return repositories.conversations


def get_document_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> DocumentRepository:
    return repositories.documents


def get_papers_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> PapersReader:
    return repositories.documents


def get_github_project_ingestion_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> GitHubProjectIngestionRepository:
    return repositories.github_ingestion


def get_github_project_enrichment_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> GitHubProjectEnrichmentRepository:
    return repositories.github_enrichment


def get_tool_website_enrichment_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> ToolWebsiteEnrichmentRepository:
    return repositories.tool_website_enrichment


def get_user_project_collection_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> UserProjectCollectionRepository:
    return repositories.project_collections


def get_github_project_recommendation_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> GitHubProjectRecommendationRepository:
    return repositories.project_recommendations


def get_github_project_semantic_source_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> GitHubProjectSemanticSourceRepository:
    return repositories.github_semantic_sources


def get_pdf_relay() -> HttpxPdfRelay:
    """Return the remote PDF streaming adapter."""
    return HttpxPdfRelay()


def get_rank_snapshot_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> RankSnapshotRepository:
    return repositories.rank_snapshots
