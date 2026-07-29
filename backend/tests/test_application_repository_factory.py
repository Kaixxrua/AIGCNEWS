from __future__ import annotations

from backend.app.repositories.application_repository_factory import (
    create_application_repositories,
    normalize_application_database_backend,
)
from backend.app.repositories.mysql_mcp_server_repository import (
    MySQLMcpServerConfigRepository,
)
from backend.app.repositories.mysql_project_write_repository import (
    MySQLProjectWriteRepository,
)
from backend.app.repositories.mysql_user_account_repository import (
    MySQLUserAccountRepository,
)
from backend.app.repositories.mysql_user_project_collection_repository import (
    MySQLUserProjectCollectionRepository,
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


class Lifecycle:
    pass


def test_backend_normalization_is_explicit() -> None:
    assert normalize_application_database_backend(None) == "mysql"
    assert normalize_application_database_backend(" POSTGRES ") == "postgres"

    try:
        normalize_application_database_backend("shadow")
    except ValueError as error:
        assert "mysql or postgres" in str(error)
    else:
        raise AssertionError("unknown application database backend was accepted")


def test_factory_builds_postgres_protocol_adapters() -> None:
    mysql = Lifecycle()
    postgres = Lifecycle()

    repositories = create_application_repositories(
        backend="postgres",
        mysql=mysql,  # type: ignore[arg-type]
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
    }
    for name, adapter in expected.items():
        repository = getattr(repositories, name)
        assert isinstance(repository, adapter)
        assert repository._database is postgres


def test_factory_preserves_mysql_compatibility_facade(monkeypatch) -> None:
    mysql = Lifecycle()
    monkeypatch.setattr(
        "backend.app.repositories.application_repository_factory.MySQLRepository._init_schema",
        lambda self: None,
    )

    repositories = create_application_repositories(
        backend="mysql",
        mysql=mysql,  # type: ignore[arg-type]
        postgres=Lifecycle(),  # type: ignore[arg-type]
    )

    assert isinstance(repositories.users, MySQLUserAccountRepository)
    assert isinstance(repositories.mcp_server_configs, MySQLMcpServerConfigRepository)
    assert isinstance(
        repositories.project_collections, MySQLUserProjectCollectionRepository
    )
    assert isinstance(repositories.github_ingestion, MySQLProjectWriteRepository)
    assert isinstance(repositories.project_recommendations, MySQLProjectWriteRepository)
    assert repositories.github_ingestion is repositories.project_recommendations
    assert repositories.users._database is mysql
    assert repositories.mcp_server_configs._database is mysql
    compatibility_databases = {
        repository._database
        for repository in (
            repositories.conversations,
            repositories.attachments,
            repositories.documents,
            repositories.ingestion_tasks,
            repositories.rank_snapshots,
            repositories.briefings,
            repositories.briefing_subscriptions,
            repositories.evaluations,
            repositories.runtime_provider_settings,
            repositories.mcp_access_tokens,
            repositories.github_ingestion,
            repositories.github_enrichment,
            repositories.tool_website_enrichment,
            repositories.project_collections,
            repositories.project_recommendations,
            repositories.github_semantic_sources,
        )
    }
    assert compatibility_databases == {mysql}
