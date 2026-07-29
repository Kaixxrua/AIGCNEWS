from __future__ import annotations

from dataclasses import dataclass

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.attachment_repository import AttachmentRepository
from backend.app.repositories.briefing_repository import (
    BriefingContentRepository,
    BriefingSubscriptionRepository,
)
from backend.app.repositories.conversation_repository import ConversationRepository
from backend.app.repositories.document_repository import DocumentRepository
from backend.app.repositories.evaluation_repository import EvaluationRepository
from backend.app.repositories.mcp_access_token_repository import McpAccessTokenRepository
from backend.app.repositories.mcp_server_repository import McpServerConfigRepository
from backend.app.repositories.postgres_attachment_repository import (
    PostgresAttachmentRepository,
)
from backend.app.repositories.postgres_briefing_repository import (
    PostgresBriefingRepository,
)
from backend.app.repositories.postgres_briefing_subscription_repository import (
    PostgresBriefingSubscriptionRepository,
)
from backend.app.repositories.postgres_conversation_repository import (
    PostgresConversationRepository,
)
from backend.app.repositories.postgres_document_repository import (
    PostgresDocumentRepository,
)
from backend.app.repositories.postgres_evaluation_repository import (
    PostgresEvaluationRepository,
)
from backend.app.repositories.postgres_github_project_semantic_repository import (
    PostgresGitHubProjectSemanticSourceRepository,
)
from backend.app.repositories.postgres_ingestion_task_repository import (
    PostgresIngestionTaskRepository,
)
from backend.app.repositories.postgres_mcp_access_token_repository import (
    PostgresMcpAccessTokenRepository,
)
from backend.app.repositories.postgres_mcp_server_repository import (
    PostgresMcpServerConfigRepository,
)
from backend.app.repositories.postgres_project_enrichment_repository import (
    PostgresGitHubProjectEnrichmentRepository,
    PostgresToolWebsiteEnrichmentRepository,
)
from backend.app.repositories.postgres_project_ingestion_repository import (
    PostgresGitHubProjectIngestionRepository,
)
from backend.app.repositories.postgres_project_write_repository import (
    PostgresProjectWriteRepository,
)
from backend.app.repositories.postgres_rank_snapshot_repository import (
    PostgresRankSnapshotRepository,
)
from backend.app.repositories.postgres_runtime_provider_repository import (
    PostgresRuntimeProviderSettingRepository,
)
from backend.app.repositories.postgres_user_account_repository import (
    PostgresUserAccountRepository,
)
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


class ApplicationIngestionTaskRepository(
    IngestionTaskWriter,
    LatestTaskReader,
    RecentTaskReader,
    MonitorTaskRepository,
    IngestionTaskAdminRepository,
):
    pass


@dataclass(frozen=True)
class ApplicationRepositories:
    users: UserAccountRepository
    conversations: ConversationRepository
    attachments: AttachmentRepository
    documents: DocumentRepository
    ingestion_tasks: ApplicationIngestionTaskRepository
    rank_snapshots: RankSnapshotRepository
    briefings: BriefingContentRepository
    briefing_subscriptions: BriefingSubscriptionRepository
    evaluations: EvaluationRepository
    runtime_provider_settings: RuntimeProviderSettingRepository
    mcp_server_configs: McpServerConfigRepository
    mcp_access_tokens: McpAccessTokenRepository
    github_ingestion: GitHubProjectIngestionRepository
    github_enrichment: GitHubProjectEnrichmentRepository
    tool_website_enrichment: ToolWebsiteEnrichmentRepository
    project_collections: UserProjectCollectionRepository
    project_recommendations: GitHubProjectRecommendationRepository
    github_semantic_sources: GitHubProjectSemanticSourceRepository


def create_application_repositories(
    *,
    postgres: PostgresDatabaseLifecycle,
) -> ApplicationRepositories:
    return ApplicationRepositories(
        users=PostgresUserAccountRepository(postgres),
        conversations=PostgresConversationRepository(postgres),
        attachments=PostgresAttachmentRepository(postgres),
        documents=PostgresDocumentRepository(postgres),
        ingestion_tasks=PostgresIngestionTaskRepository(postgres),
        rank_snapshots=PostgresRankSnapshotRepository(postgres),
        briefings=PostgresBriefingRepository(postgres),
        briefing_subscriptions=PostgresBriefingSubscriptionRepository(postgres),
        evaluations=PostgresEvaluationRepository(postgres),
        runtime_provider_settings=PostgresRuntimeProviderSettingRepository(postgres),
        mcp_server_configs=PostgresMcpServerConfigRepository(postgres),
        mcp_access_tokens=PostgresMcpAccessTokenRepository(postgres),
        github_ingestion=PostgresGitHubProjectIngestionRepository(postgres),
        github_enrichment=PostgresGitHubProjectEnrichmentRepository(postgres),
        tool_website_enrichment=PostgresToolWebsiteEnrichmentRepository(postgres),
        project_collections=PostgresProjectWriteRepository(postgres),
        project_recommendations=PostgresProjectWriteRepository(postgres),
        github_semantic_sources=PostgresGitHubProjectSemanticSourceRepository(postgres),
    )
