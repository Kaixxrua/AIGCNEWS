from __future__ import annotations

import asyncio
from typing import Any, Mapping

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
    DocumentXSnapshotBackfillReader,
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
from backend.app.repositories.push_channel_repository import PushChannelRepository
from backend.app.repositories.rank_snapshot_repository import RankSnapshotRepository
from backend.app.repositories.runtime_provider_repository import (
    RuntimeProviderSettingRepository,
)
from backend.app.repositories.scheduler_job_config_repository import (
    SchedulerJobConfigRepository,
)
from backend.app.repositories.task_repository import (
    IngestionTaskAdminRepository,
)
from backend.app.repositories.user_account_repository import UserAccountRepository
from backend.app.repositories.user_subscription_repository import (
    UserSubscriptionRepository,
)
from backend.app.repositories.wechat_account_repository import (
    WeChatOfficialAccountRepository,
)
from backend.app.repositories.wechat_article_repository import WeChatArticleRepository
from backend.app.repositories.wechat_follow_repository import WeChatFollowRepository
from backend.app.repositories.wechat_session_repository import (
    WeChatLoginAttemptRepository,
    WeChatSessionRepository,
)
from backend.app.repositories.x_credentials_repository import XCredentialRepository
from backend.app.repositories.x_watch_repository import XWatchAccountRepository
from backend.app.services.briefing.composition import provide_daily_briefing_service
from backend.app.services.briefing.daily_briefing import DailyBriefingService
from backend.app.services.briefing_admin import BriefingAdminService
from backend.app.services.chat.conversation_service import ConversationService
from backend.app.services.dashboard_cache_admin import DashboardCacheAdminService
from backend.app.services.data_cleanup_admin import DataCleanupAdminService
from backend.app.services.github_project_admin import GitHubProjectAdminService
from backend.app.services.github_project_crawl_admin import (
    GitHubProjectCrawlAdminService,
)
from backend.app.services.github_project_recommendation_admin import (
    GitHubProjectRecommendationAdminService,
)
from backend.app.services.ingestion_admin import IngestionAdminService
from backend.app.services.mcp.admin_service import McpAdminService
from backend.app.services.ops_diagnostics import OpsDiagnosticsService
from backend.app.services.papers.pdf_relay import HttpxPdfRelay
from backend.app.services.personal_projects import PersonalProjectsService
from backend.app.services.push.channel_service import PushChannelService
from backend.app.services.push.subscription_service import UserSubscriptionService
from backend.app.services.rag.chat_service import ChatService
from backend.app.services.rag.composition import RagChatServiceProvider
from backend.app.services.runtime_provider.admin_service import (
    RuntimeProviderAdminService,
)
from backend.app.services.runtime_provider.runtime import (
    ApplicationModelProviderRuntime,
)
from backend.app.services.scheduler_admin import SchedulerAdminService
from backend.app.services.scheduler_config_admin import SchedulerConfigAdminService
from backend.app.services.wechat.account_service import WeChatAccountService
from backend.app.services.wechat.follow_service import WeChatFollowService
from backend.app.services.wechat.login_service import WeChatLoginService
from backend.app.services.wechat.sync_service import WeChatSyncService
from backend.app.services.wechat.transport import WeChatMpTransport
from backend.app.services.x_credentials.admin_service import XCredentialAdminService
from backend.app.services.x_snapshot_admin import XSnapshotAdminService
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


def get_github_project_crawl_admin_service(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> GitHubProjectCrawlAdminService:
    return GitHubProjectCrawlAdminService(repositories)


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


def get_x_credential_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> XCredentialRepository:
    return repositories.x_credentials


def get_optional_x_credential_repository(
    request: Request,
) -> XCredentialRepository | None:
    """Return the DB credential store when the application runtime is available.

    The optional form preserves the legacy X watch probe dependency seam used by
    isolated route tests and by older callers that still rely on env credentials.
    Production composition always provides ``application_repositories``.
    """
    repositories = getattr(request.app.state, "application_repositories", None)
    return repositories.x_credentials if repositories is not None else None


def get_x_operation_lock(request: Request) -> asyncio.Lock:
    """Return the shared X/Twitter operation lock from the app runtime.

    If the application runtime is not configured (e.g. isolated route tests),
    return a fresh lock so endpoints remain testable without a scheduler.
    """
    lock = getattr(request.app.state, "x_operation_lock", None)
    if isinstance(lock, asyncio.Lock):
        return lock
    return asyncio.Lock()


def get_x_watch_admin_service(
    repository: XWatchAccountRepository = Depends(get_x_watch_account_repository),
    credential_repository: XCredentialRepository | None = Depends(
        get_optional_x_credential_repository
    ),
    x_lock: asyncio.Lock = Depends(get_x_operation_lock),
) -> XWatchAdminService:
    from backend.app.services.x_watch.probe import test_x_watch_account

    def tester(handle: str) -> Mapping[str, Any]:
        if credential_repository is None:
            return test_x_watch_account(handle)
        credentials = credential_repository.list_enabled_x_credentials()
        if not credentials:
            return {"status": "failed", "message": "x_auth_not_configured"}
        return test_x_watch_account(handle, credentials[0])

    return XWatchAdminService(repository, tester, x_lock=x_lock)


def get_x_credential_admin_service(
    repository: XCredentialRepository = Depends(get_x_credential_repository),
    watch_repository: XWatchAccountRepository = Depends(get_x_watch_account_repository),
    x_lock: asyncio.Lock = Depends(get_x_operation_lock),
) -> XCredentialAdminService:
    from backend.app.services.x_credentials.probe import probe_x_credential

    def tester(credential: Mapping[str, Any], handle: str) -> Mapping[str, Any]:
        return probe_x_credential(credential, handle)

    return XCredentialAdminService(repository, tester, x_lock=x_lock)


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


def get_scheduler_config_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> SchedulerJobConfigRepository:
    return repositories.scheduler_job_configs


def get_scheduler_config_admin_service(
    repository: SchedulerJobConfigRepository = Depends(get_scheduler_config_repository),
) -> SchedulerConfigAdminService:
    return SchedulerConfigAdminService(repository)


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


def get_x_snapshot_admin_service(
    documents: DocumentXSnapshotBackfillReader = Depends(get_document_repository),
    rank_snapshots: RankSnapshotRepository = Depends(get_rank_snapshot_repository),
) -> XSnapshotAdminService:
    return XSnapshotAdminService(documents=documents, rank_snapshots=rank_snapshots)


def get_wechat_login_attempt_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> WeChatLoginAttemptRepository:
    return repositories.wechat_login_attempts


def get_wechat_session_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> WeChatSessionRepository:
    return repositories.wechat_sessions


def get_wechat_account_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> WeChatOfficialAccountRepository:
    return repositories.wechat_accounts


def get_wechat_article_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> WeChatArticleRepository:
    return repositories.wechat_articles


def get_wechat_follow_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> WeChatFollowRepository:
    return repositories.wechat_follows


def get_wechat_mp_transport() -> WeChatMpTransport:
    from backend.app.core.config import settings

    return WeChatMpTransport(proxy=settings.outbound_proxy or None)


def get_wechat_login_service(
    attempts: WeChatLoginAttemptRepository = Depends(get_wechat_login_attempt_repository),
    sessions: WeChatSessionRepository = Depends(get_wechat_session_repository),
    transport: WeChatMpTransport = Depends(get_wechat_mp_transport),
) -> WeChatLoginService:
    from backend.app.core.config import settings

    return WeChatLoginService(
        attempts,
        sessions,
        transport,
        login_attempt_ttl_seconds=int(
            getattr(settings, "wechat_login_attempt_ttl_seconds", 300)
        ),
    )


def get_wechat_account_service(
    accounts: WeChatOfficialAccountRepository = Depends(get_wechat_account_repository),
    sessions: WeChatSessionRepository = Depends(get_wechat_session_repository),
    transport: WeChatMpTransport = Depends(get_wechat_mp_transport),
) -> WeChatAccountService:
    return WeChatAccountService(accounts, sessions, transport)


def get_wechat_sync_service(
    accounts: WeChatOfficialAccountRepository = Depends(get_wechat_account_repository),
    articles: WeChatArticleRepository = Depends(get_wechat_article_repository),
    sessions: WeChatSessionRepository = Depends(get_wechat_session_repository),
    transport: WeChatMpTransport = Depends(get_wechat_mp_transport),
    operations_runtime: ApplicationOperationsRuntime = Depends(get_operations_runtime),
) -> WeChatSyncService:
    from backend.app.core.config import settings
    from backend.app.services.wechat_sogou.transport import SogouWechatTransport

    return WeChatSyncService(
        accounts,
        articles,
        sessions,
        transport,
        operations_runtime,
        max_pages=int(getattr(settings, "wechat_sync_max_pages", 20)),
        max_articles=int(getattr(settings, "wechat_sync_max_articles", 500)),
        inter_page_delay_seconds=float(
            getattr(settings, "wechat_sync_inter_page_delay_seconds", 1.0)
        ),
        # Direct connection: Sogou/mp are domestic targets; routing them
        # through the overseas outbound proxy worsens anti-bot risk control.
        sogou_transport=SogouWechatTransport(),
        sogou_max_pages=int(getattr(settings, "wechat_sogou_sync_max_pages", 2)),
        sogou_max_articles=int(getattr(settings, "wechat_sogou_sync_max_articles", 20)),
        sogou_request_delay_seconds=float(
            getattr(settings, "wechat_sogou_sync_request_delay_seconds", 1.5)
        ),
    )


def get_wechat_follow_service(
    follows: WeChatFollowRepository = Depends(get_wechat_follow_repository),
    articles: WeChatArticleRepository = Depends(get_wechat_article_repository),
) -> WeChatFollowService:
    return WeChatFollowService(follows, articles)


def get_push_channel_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> PushChannelRepository:
    return repositories.push_channels


def get_user_subscription_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> UserSubscriptionRepository:
    return repositories.user_subscriptions


def get_push_channel_service(
    channels: PushChannelRepository = Depends(get_push_channel_repository),
) -> PushChannelService:
    return PushChannelService(channels)


def get_user_subscription_service(
    subscriptions: UserSubscriptionRepository = Depends(
        get_user_subscription_repository
    ),
    channels: PushChannelRepository = Depends(get_push_channel_repository),
) -> UserSubscriptionService:
    return UserSubscriptionService(subscriptions, channels)
