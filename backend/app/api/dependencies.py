from __future__ import annotations

import logging
from typing import Any, Mapping

from fastapi import Depends, Request

from backend.app.core.operations import ApplicationOperationsRuntime
from backend.app.core.postgres_database import PostgresDatabaseLifecycle
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
from backend.app.repositories.email_pool_settings_repository import (
    EmailPoolSettingsRepository,
)
from backend.app.repositories.error_event_repository import ErrorEventRepository
from backend.app.repositories.evaluation_repository import EvaluationRepository
from backend.app.repositories.feed_token_repository import FeedTokenRepository
from backend.app.repositories.mcp_access_token_repository import (
    McpAccessTokenRepository,
)
from backend.app.repositories.mcp_server_repository import McpServerConfigRepository
from backend.app.repositories.oauth_identity_repository import OAuthIdentityRepository
from backend.app.repositories.oauth_settings_repository import OAuthSettingsRepository
from backend.app.repositories.payment_order_repository import PaymentOrderRepository
from backend.app.repositories.payment_plan_overrides_repository import (
    PaymentPlanOverridesRepository,
)
from backend.app.repositories.payment_settings_repository import PaymentSettingsRepository
from backend.app.repositories.project_catalog_factory import (
    get_project_catalog_repository,
)
from backend.app.repositories.project_write_repository import (
    GitHubProjectEnrichmentRepository,
    GitHubProjectIngestionRepository,
    GitHubProjectRecommendationRepository,
    GitHubProjectSemanticSourceRepository,
    ToolWebsiteEnrichmentRepository,
    UserProjectCollectionRepository,
)
from backend.app.repositories.push_channel_repository import PushChannelRepository
from backend.app.repositories.push_delivery_repository import PushDeliveryRepository
from backend.app.repositories.rank_snapshot_repository import RankSnapshotRepository
from backend.app.repositories.runtime_provider_repository import (
    RuntimeProviderSettingRepository,
)
from backend.app.repositories.scheduler_job_config_repository import (
    SchedulerJobConfigRepository,
)
from backend.app.repositories.site_contact_page_repository import SiteContactPageRepository
from backend.app.repositories.smtp_settings_repository import SmtpSettingsRepository
from backend.app.repositories.task_repository import (
    IngestionTaskAdminRepository,
)
from backend.app.repositories.telegram_link_attempt_repository import TelegramLinkAttemptRepository
from backend.app.repositories.telegram_settings_repository import TelegramSettingsRepository
from backend.app.repositories.user_account_repository import UserAccountRepository
from backend.app.repositories.user_subscription_repository import (
    UserSubscriptionRepository,
)
from backend.app.repositories.x_credentials_repository import XCredentialRepository
from backend.app.repositories.x_translation_repository import XTranslationTaskRepository
from backend.app.repositories.x_watch_repository import XWatchAccountRepository
from backend.app.services.auth.oauth.config_admin import OAuthConfigAdminService
from backend.app.services.briefing.composition import provide_daily_briefing_service
from backend.app.services.briefing.daily_briefing import DailyBriefingService
from backend.app.services.briefing.dispatch import build_briefing_saved_notifier
from backend.app.services.briefing_admin import BriefingAdminService
from backend.app.services.chat.conversation_service import ConversationService
from backend.app.services.dashboard.query_service import GitHubHotBoardReader
from backend.app.services.dashboard_cache_admin import DashboardCacheAdminService
from backend.app.services.data_cleanup_admin import DataCleanupAdminService
from backend.app.services.email_pool_config_admin import EmailPoolConfigAdminService
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
from backend.app.services.payments.config_admin import PaymentConfigAdminService
from backend.app.services.payments.plan_overrides_admin import PaymentPlanOverridesAdminService
from backend.app.services.payments.providers.base import PaymentProvider
from backend.app.services.payments.providers.registry import build_payment_providers
from backend.app.services.payments.runtime_config import resolve_payment_config
from backend.app.services.personal_projects import PersonalProjectsService
from backend.app.services.project_adoptions import ProjectAdoptionService
from backend.app.services.project_catalog.query_service import ProjectCatalogQueryService
from backend.app.services.project_catalog.trends_service import ProjectTrendsService
from backend.app.services.push.channel_service import PushChannelService
from backend.app.services.push.subscription_service import UserSubscriptionService
from backend.app.services.push.telegram_config_admin import TelegramConfigAdminService
from backend.app.services.push.telegram_service import TelegramLinkService
from backend.app.services.rag.chat_service import ChatService
from backend.app.services.rag.composition import RagChatServiceProvider
from backend.app.services.report.subscription_plan_service import (
    ReportSubscriptionPlanService,
)
from backend.app.services.runtime_provider.admin_service import (
    RuntimeProviderAdminService,
)
from backend.app.services.runtime_provider.runtime import (
    ApplicationModelProviderRuntime,
)
from backend.app.services.scheduler_admin import SchedulerAdminService
from backend.app.services.scheduler_config_admin import SchedulerConfigAdminService
from backend.app.services.smtp_config_admin import SmtpConfigAdminService
from backend.app.services.x_credentials.admin_service import XCredentialAdminService
from backend.app.services.x_snapshot_admin import XSnapshotAdminService
from backend.app.services.x_watch.admin_service import XWatchAdminService

logger = logging.getLogger(__name__)


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


def get_oauth_identity_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> OAuthIdentityRepository:
    return repositories.oauth_identities


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
    request: Request,
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> DailyBriefingService:
    # 生成是主功能、补发是次功能：operations runtime 缺失时降级为不挂通知，
    # 绝不让补发接线问题阻断简报生成（运维台运行时始终存在，仅测试桩缺失）。
    runtime = getattr(request.app.state, "operations_runtime", None)
    notifier = None
    if isinstance(runtime, ApplicationOperationsRuntime):
        notifier = build_briefing_saved_notifier(
            repositories,
            operations=runtime,
            redis_client=getattr(request.app.state, "redis", None),
        )
    else:
        logger.warning(
            "[Briefing] operations runtime 未配置，简报保存后将跳过订阅补发通知"
        )
    return provide_daily_briefing_service(
        repositories=repositories, briefing_saved=notifier
    )


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


def get_x_translation_task_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> XTranslationTaskRepository:
    return repositories.x_translation_tasks


def get_x_watch_account_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> XWatchAccountRepository:
    return repositories.x_watch_accounts


def get_optional_x_watch_account_repository(
    request: Request,
) -> XWatchAccountRepository | None:
    """Return the watchlist store when the application runtime is available.

    Dashboard contract tests intentionally mount the router without the full
    repository container. Production always provides it; the optional seam
    keeps those isolated readers and older compositions compatible.
    """
    repositories = getattr(request.app.state, "application_repositories", None)
    return repositories.x_watch_accounts if repositories is not None else None


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


def get_x_watch_admin_service(
    repository: XWatchAccountRepository = Depends(get_x_watch_account_repository),
    credential_repository: XCredentialRepository | None = Depends(
        get_optional_x_credential_repository
    ),
) -> XWatchAdminService:
    from backend.app.services.x_watch.probe import test_x_watch_account

    def tester(handle: str) -> Mapping[str, Any]:
        if credential_repository is None:
            return test_x_watch_account(handle)
        credentials = credential_repository.list_enabled_x_credentials()
        if not credentials:
            return {"status": "failed", "message": "x_auth_not_configured"}
        return test_x_watch_account(handle, credentials[0])

    # 手动单账号测活只发 1-2 次请求，与采集并发互不干扰；不占用 X 操作大锁
    # （大锁留给采集/回填/凭证池测活等重路径，防止共享出口 IP 上 429 叠加放大）。
    return XWatchAdminService(repository, tester)


def get_x_credential_admin_service(
    repository: XCredentialRepository = Depends(get_x_credential_repository),
    watch_repository: XWatchAccountRepository = Depends(get_x_watch_account_repository),
) -> XCredentialAdminService:
    from backend.app.services.x_credentials.probe import probe_x_credential

    def tester(credential: Mapping[str, Any], handle: str) -> Mapping[str, Any]:
        return probe_x_credential(credential, handle)

    # 与上同理：手动单凭证测试走轻量并发道，不排在采集大锁后面。
    return XCredentialAdminService(repository, tester)


def get_mcp_access_token_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> McpAccessTokenRepository:
    return repositories.mcp_access_tokens


def get_feed_token_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> FeedTokenRepository:
    return repositories.feed_tokens


def get_user_account_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> UserAccountRepository:
    return repositories.users


def get_payment_order_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> PaymentOrderRepository:
    return repositories.orders


def get_payment_settings_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> PaymentSettingsRepository:
    return repositories.payment_settings


def get_oauth_settings_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> OAuthSettingsRepository:
    return repositories.oauth_settings


def get_oauth_config_admin_service(
    repository: OAuthSettingsRepository = Depends(get_oauth_settings_repository),
) -> OAuthConfigAdminService:
    return OAuthConfigAdminService(repository)


def get_payment_config_admin_service(
    repository: PaymentSettingsRepository = Depends(get_payment_settings_repository),
) -> PaymentConfigAdminService:
    return PaymentConfigAdminService(repository)


def get_payment_plan_overrides_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> PaymentPlanOverridesRepository:
    return repositories.payment_plan_overrides


def get_payment_plan_overrides_admin_service(
    repository: PaymentPlanOverridesRepository = Depends(get_payment_plan_overrides_repository),
) -> PaymentPlanOverridesAdminService:
    return PaymentPlanOverridesAdminService(repository)


def get_payment_providers() -> dict[str, PaymentProvider]:
    """Build providers from the request-time effective payment configuration."""
    return build_payment_providers(resolve_payment_config())


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


def get_smtp_settings_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> SmtpSettingsRepository:
    return repositories.smtp_settings


def get_smtp_config_admin_service(
    repository: SmtpSettingsRepository = Depends(get_smtp_settings_repository),
) -> SmtpConfigAdminService:
    return SmtpConfigAdminService(repository)


def get_email_pool_settings_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> EmailPoolSettingsRepository:
    return repositories.email_pool_settings


def get_email_pool_config_admin_service(
    request: Request,
    repository: EmailPoolSettingsRepository = Depends(
        get_email_pool_settings_repository
    ),
) -> EmailPoolConfigAdminService:
    # 测试投递走真实池链路，需要 redis 支撑配额计数；未就绪时 None 即
    # fail-open（护栏失效但发送可用），与 pool_transport 契约一致
    return EmailPoolConfigAdminService(
        repository, redis_client=getattr(request.app.state, "redis", None)
    )


def get_push_delivery_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> PushDeliveryRepository:
    return repositories.push_deliveries


def get_site_contact_page_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> SiteContactPageRepository:
    return repositories.site_contact_page


def get_error_event_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> ErrorEventRepository:
    return repositories.error_events


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


def get_document_vector_repository():
    """Return the legacy document-level semantic reader for dashboard search."""
    from backend.app.repositories.milvus_repo import MilvusRepository

    return MilvusRepository()


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


def get_project_catalog_query_service() -> ProjectCatalogQueryService:
    """公共项目目录查询编排服务；仓储仍经工厂按次解析，保持既有连接语义。"""
    return ProjectCatalogQueryService(repository_factory=get_project_catalog_repository)


# 全进程一份：昨日名次在服务里缓存十分钟，按请求新建就留不住。
_project_trends_service = ProjectTrendsService()


def get_project_trends_service() -> ProjectTrendsService:
    """项目库榜单行情：近 N 天星标与日增、今日热榜的昨日名次。"""
    return _project_trends_service


def get_project_adoption_service() -> ProjectAdoptionService:
    """采纳回执编排服务；仓储经工厂按次解析，与目录查询同一连接语义。"""
    return ProjectAdoptionService()


def get_github_hot_board_reader() -> GitHubHotBoardReader:
    """看板 github 榜的日度热度读取（项目库目录仓储结构式满足该协议）。

    经工厂按次解析，与 get_project_catalog_query_service 同一连接语义；
    协议窄化到看板所需的两个方法，便于路由测试用假实现替换。
    """
    return get_project_catalog_repository()


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
    catalog: ProjectCatalogQueryService = Depends(get_project_catalog_query_service),
) -> GitHubProjectRecommendationAdminService:
    return GitHubProjectRecommendationAdminService(recommendations, enrichment, catalog)


def get_github_project_semantic_source_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> GitHubProjectSemanticSourceRepository:
    return repositories.github_semantic_sources




def get_rank_snapshot_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> RankSnapshotRepository:
    return repositories.rank_snapshots


def get_x_snapshot_admin_service(
    documents: DocumentXSnapshotBackfillReader = Depends(get_document_repository),
    rank_snapshots: RankSnapshotRepository = Depends(get_rank_snapshot_repository),
) -> XSnapshotAdminService:
    return XSnapshotAdminService(documents=documents, rank_snapshots=rank_snapshots)


def get_postgres_database(request: Request) -> PostgresDatabaseLifecycle:
    database = getattr(request.app.state, "postgres_database", None)
    if database is None:
        raise RuntimeError("PostgreSQL database lifecycle is not configured")
    return database


def get_report_subscription_plan_service(
    request: Request,
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> ReportSubscriptionPlanService:
    return ReportSubscriptionPlanService(
        database=get_postgres_database(request),
        briefing_subscriptions=repositories.briefing_subscriptions,
        user_subscriptions=repositories.user_subscriptions,
        push_channels=repositories.push_channels,
    )


def get_push_channel_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> PushChannelRepository:
    return repositories.push_channels


def get_user_subscription_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> UserSubscriptionRepository:
    return repositories.user_subscriptions


def get_telegram_link_attempt_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> TelegramLinkAttemptRepository:
    return repositories.telegram_link_attempts


def get_push_channel_service(
    channels: PushChannelRepository = Depends(get_push_channel_repository),
) -> PushChannelService:
    return PushChannelService(channels)


def get_telegram_link_service(
    attempts: TelegramLinkAttemptRepository = Depends(
        get_telegram_link_attempt_repository
    ),
    channels: PushChannelRepository = Depends(get_push_channel_repository),
) -> TelegramLinkService:
    return TelegramLinkService(attempts=attempts, channels=channels)


def get_telegram_settings_repository(
    repositories: ApplicationRepositories = Depends(get_application_repositories),
) -> TelegramSettingsRepository:
    return repositories.telegram_settings


def get_telegram_config_admin_service(
    repository: TelegramSettingsRepository = Depends(get_telegram_settings_repository),
) -> TelegramConfigAdminService:
    return TelegramConfigAdminService(repository)


def get_user_subscription_service(
    subscriptions: UserSubscriptionRepository = Depends(
        get_user_subscription_repository
    ),
    channels: PushChannelRepository = Depends(get_push_channel_repository),
) -> UserSubscriptionService:
    return UserSubscriptionService(subscriptions, channels)
