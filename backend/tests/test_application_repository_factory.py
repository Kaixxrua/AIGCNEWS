from __future__ import annotations

from backend.app.repositories.application_repository_factory import (
    create_application_repositories,
)
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
from backend.app.repositories.postgres_x_watch_repository import (
    PostgresXWatchAccountRepository,
)


class Lifecycle:
    pass


def test_factory_builds_postgres_protocol_adapters() -> None:
    postgres = Lifecycle()

    repositories = create_application_repositories(
        postgres=postgres,  # type: ignore[arg-type]
    )

    expected = {
        "users": PostgresUserAccountRepository,
        "conversations": PostgresConversationRepository,
        "attachments": PostgresAttachmentRepository,
        "documents": PostgresDocumentRepository,
        "ingestion_tasks": PostgresIngestionTaskRepository,
        "rank_snapshots": PostgresRankSnapshotRepository,
        "briefings": PostgresBriefingRepository,
        "briefing_subscriptions": PostgresBriefingSubscriptionRepository,
        "evaluations": PostgresEvaluationRepository,
        "runtime_provider_settings": PostgresRuntimeProviderSettingRepository,
        "mcp_server_configs": PostgresMcpServerConfigRepository,
        "mcp_access_tokens": PostgresMcpAccessTokenRepository,
        "github_ingestion": PostgresGitHubProjectIngestionRepository,
        "github_enrichment": PostgresGitHubProjectEnrichmentRepository,
        "tool_website_enrichment": PostgresToolWebsiteEnrichmentRepository,
        "project_collections": PostgresProjectWriteRepository,
        "project_recommendations": PostgresProjectWriteRepository,
        "github_semantic_sources": PostgresGitHubProjectSemanticSourceRepository,
        "x_watch_accounts": PostgresXWatchAccountRepository,
    }
    for name, adapter in expected.items():
        repository = getattr(repositories, name)
        assert isinstance(repository, adapter)
        assert repository._database is postgres
