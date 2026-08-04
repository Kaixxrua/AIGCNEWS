from __future__ import annotations

from typing import Any

from fastapi import Depends, Request

from backend.app.core.operations import ApplicationOperationsRuntime
from backend.app.core.redis_client import close_redis_client, create_redis_client
from backend.app.monitoring.health import HealthCheckService, ReadinessCheck
from backend.app.repositories.application_repository_factory import (
    ApplicationIngestionTaskRepository,
    ApplicationRepositories,
)
from backend.app.repositories.briefing_repository import (
    BriefingContentRepository,
    BriefingSubscriptionRepository,
)
from backend.app.repositories.conversation_repository import ConversationRepository
from backend.app.repositories.document_repository import (
    DocumentAdminWriter,
    DocumentRepository,
    PapersReader,
)
from backend.app.repositories.evaluation_repository import EvaluationRepository
from backend.app.repositories.mcp_access_token_repository import (
    McpAccessTokenRepository,
)
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
)
from backend.app.repositories.user_account_repository import UserAccountRepository
from backend.app.repositories.x_watch_repository import XWatchAccountRepository
from backend.app.services.briefing.composition import provide_daily_briefing_service
from backend.app.services.briefing.daily_briefing import DailyBriefingService
from backend.app.services.briefing_admin import BriefingAdminService
from backend.app.services.chat.conversation_service import ConversationService
from backend.app.services.dashboard_cache_admin import DashboardCacheAdminService
from backend.app.services.data_cleanup_admin import DataCleanupAdminService
from backend.app.services.github_project_admin import GitHubProjectAdminService
from backend.app.services.github_project_recommendation_admin import (
    GitHubProjectRecommendationAdminService,
)
from backend.app.services.ingestion_admin import IngestionAdminService
from backend.app.services.mcp.admin_service import McpAdminService
from backend.app.services.ops_diagnostics import OpsDiagnosticsService
from backend.app.services.papers.pdf_relay import HttpxPdfRelay
from backend.app.services.personal_projects import PersonalProjectsService
from backend.app.services.rag.chat_service import ChatService
from backend.app.services.rag.composition import RagChatServiceProvider
from backend.app.services.runtime_provider.admin_service import (
    RuntimeProviderAdminService,
)
from backend.app.services.runtime_provider.runtime import (
    ApplicationModelProviderRuntime,
)
from backend.app.services.scheduler_admin import SchedulerAdminService
from backend.app.services.x_watch.admin_service import XWatchAdminService


def get_monitoring_runtime(request: Request) -> Any:
    runtime = getattr(request.app.state, "monitoring_runtime", None)
    if runtime is None:
        raise RuntimeError("Application monitoring is not configured")
    return runtime


def get_health_check_service(request: Request) -> HealthCheckService:
    return get_monitoring_runtime(request).health_checks


def get_readiness_check(request: Request) -> ReadinessCheck:
    return get_monitoring_runtime(request).readiness


def get_application_repositories(request: Request) -> ApplicationRepositories:
    repositories = getattr(request.app.state, "application_repositories", None)
    if repositories is None:
        raise RuntimeError("Application repositories are not configured")
    return repositories


def get_ingestion_task_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> ApplicationIngestionTaskRepository:
    return repositories.ingestion_tasks


def get_ingestion_admin_service(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> IngestionAdminService:
    return IngestionAdminService(repositories)


def get_github_project_admin_service(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> GitHubProjectAdminService:
    return GitHubProjectAdminService(repositories)


def get_briefing_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> BriefingContentRepository:
    return repositories.briefings


def get_briefing_subscription_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> BriefingSubscriptionRepository:
    return repositories.briefing_subscriptions


def get_daily_briefing_service(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> DailyBriefingService:
    return provide_daily_briefing_service(repositories=repositories)


def get_briefing_admin_service(
    briefing: DailyBriefingService = Depends(get_daily_briefing_service),
) -> BriefingAdminService:
    return BriefingAdminService(briefing)


def get_evaluation_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> EvaluationRepository:
    return repositories.evaluations


def get_mcp_server_config_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> McpServerConfigRepository:
    return repositories.mcp_server_configs


def get_mcp_admin_service(
    repository: McpServerConfigRepository = Depends(get_mcp_server_config_repository),
) -> McpAdminService:
    from backend.app.services.mcp_connection_tester import test_mcp_server_connection

    return McpAdminService(repository, test_mcp_server_connection)


def get_x_watch_account_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> XWatchAccountRepository:
    return repositories.x_watch_accounts


def get_x_watch_admin_service(
    repository: XWatchAccountRepository = Depends(get_x_watch_account_repository),
) -> XWatchAdminService:
    from backend.app.services.x_watch.probe import test_x_watch_account

    return XWatchAdminService(repository, test_x_watch_account)


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


def get_model_provider_runtime(request: Request) -> ApplicationModelProviderRuntime:
    runtime = getattr(request.app.state, "model_provider_runtime", None)
    if not isinstance(runtime, ApplicationModelProviderRuntime):
        raise RuntimeError("Application model provider runtime is not configured")
    return runtime


def get_optional_model_provider_runtime(
    request: Request,
) -> ApplicationModelProviderRuntime | None:
    runtime = getattr(request.app.state, "model_provider_runtime", None)
    return runtime if isinstance(runtime, ApplicationModelProviderRuntime) else None


def get_runtime_provider_admin_service(
    repository: RuntimeProviderSettingRepository = Depends(
        get_runtime_provider_setting_repository
    ),
    runtime: ApplicationModelProviderRuntime | None = Depends(
        get_optional_model_provider_runtime
    ),
) -> RuntimeProviderAdminService:
    invalidate_models = (
        runtime.invalidate if isinstance(runtime, ApplicationModelProviderRuntime) else None
    )
    return RuntimeProviderAdminService(repository, invalidate_models=invalidate_models)


def get_conversation_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> ConversationRepository:
    return repositories.conversations


def get_conversation_service(
    repository: ConversationRepository = Depends(get_conversation_repository),
) -> ConversationService:
    return ConversationService(repository)


def get_rag_chat_service(request: Request) -> ChatService:
    provider = getattr(request.app.state, "rag_chat_service_provider", None)
    if not isinstance(provider, RagChatServiceProvider):
        raise RuntimeError("RAG chat service provider is not configured")
    return provider.get()


def get_project_search_runtime(request: Request) -> Any:
    runtime = getattr(request.app.state, "project_search_runtime", None)
    if runtime is None:
        raise RuntimeError("Project search runtime is not configured")
    return runtime


def get_operations_runtime(request: Request) -> ApplicationOperationsRuntime:
    runtime = getattr(request.app.state, "operations_runtime", None)
    if not isinstance(runtime, ApplicationOperationsRuntime):
        raise RuntimeError("Application operations runtime is not configured")
    return runtime


def get_scheduler_admin_service(request: Request) -> SchedulerAdminService:
    runtime = getattr(request.app.state, "scheduler_runtime", None)
    if runtime is None:
        raise RuntimeError("Application scheduler is not configured")
    return SchedulerAdminService(runtime.scheduler)


def get_ops_diagnostics_service(request: Request) -> OpsDiagnosticsService:
    from backend.app.core.config import settings
    from backend.app.domain.project_taxonomy import WEBSITE_TAXONOMY
    from backend.app.services.project_catalog_readiness import (
        project_catalog_runtime_readiness,
    )

    runtime = getattr(request.app.state, "project_search_runtime", None)
    if runtime is None:
        raise RuntimeError("Project search runtime is not configured")
    return OpsDiagnosticsService(
        readiness=project_catalog_runtime_readiness,
        shadow_snapshot=runtime.project_search_shadow_snapshot,
        shadow_finalizer=runtime.finalize_project_search_shadow,
        shadow_shutdown_timeout=float(
            settings.project_search_shadow_shutdown_timeout_seconds
        ),
        website_taxonomy=WEBSITE_TAXONOMY,
    )


def get_dashboard_cache_admin_service() -> DashboardCacheAdminService:
    from fastapi_cache import FastAPICache

    return DashboardCacheAdminService(
        create_redis_client,
        close_redis_client,
        cache_prefix=getattr(FastAPICache, "_prefix", "") or "",
    )


def get_document_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> DocumentRepository:
    return repositories.documents


def get_papers_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> PapersReader:
    return repositories.documents


def get_data_cleanup_admin_service(
    documents: DocumentAdminWriter = Depends(get_document_repository),
    tasks: IngestionTaskAdminRepository = Depends(get_ingestion_task_repository),
) -> DataCleanupAdminService:
    from backend.app.repositories.milvus_repo import MilvusRepository

    return DataCleanupAdminService(documents, tasks, MilvusRepository())


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


def get_personal_projects_service(
    collection: UserProjectCollectionRepository = Depends(
        get_user_project_collection_repository
    ),
    enrichment: ToolWebsiteEnrichmentRepository = Depends(
        get_tool_website_enrichment_repository
    ),
) -> PersonalProjectsService:
    return PersonalProjectsService(collection=collection, enrichment=enrichment)


def get_github_project_recommendation_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> GitHubProjectRecommendationRepository:
    return repositories.project_recommendations


def get_github_project_recommendation_admin_service(
    recommendations: GitHubProjectRecommendationRepository = Depends(
        get_github_project_recommendation_repository
    ),
    enrichment: GitHubProjectEnrichmentRepository = Depends(
        get_github_project_enrichment_repository
    ),
) -> GitHubProjectRecommendationAdminService:
    return GitHubProjectRecommendationAdminService(recommendations, enrichment)


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
