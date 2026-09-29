from __future__ import annotations

import os
from dataclasses import dataclass

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.attachment_repository import AttachmentRepository
from backend.app.repositories.briefing_repository import (
    BriefingContentRepository,
    BriefingSubscriptionRepository,
)
from backend.app.repositories.conversation_repository import ConversationRepository
from backend.app.repositories.document_repository import DocumentRepository
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
from backend.app.repositories.postgres_email_pool_settings_repository import (
    PostgresEmailPoolSettingsRepository,
)
from backend.app.repositories.postgres_error_event_repository import (
    PostgresErrorEventRepository,
)
from backend.app.repositories.postgres_evaluation_repository import (
    PostgresEvaluationRepository,
)
from backend.app.repositories.postgres_feed_token_repository import (
    PostgresFeedTokenRepository,
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
from backend.app.repositories.postgres_oauth_identity_repository import (
    PostgresOAuthIdentityRepository,
)
from backend.app.repositories.postgres_oauth_settings_repository import (
    PostgresOAuthSettingsRepository,
)
from backend.app.repositories.postgres_payment_order_repository import (
    PostgresPaymentOrderRepository,
)
from backend.app.repositories.postgres_payment_plan_overrides_repository import (
    PostgresPaymentPlanOverridesRepository,
)
from backend.app.repositories.postgres_payment_settings_repository import (
    PostgresPaymentSettingsRepository,
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
from backend.app.repositories.postgres_push_channel_repository import (
    PostgresPushChannelRepository,
)
from backend.app.repositories.postgres_push_delivery_repository import (
    PostgresPushDeliveryRepository,
)
from backend.app.repositories.postgres_rank_snapshot_repository import (
    PostgresRankSnapshotRepository,
)
from backend.app.repositories.postgres_runtime_provider_repository import (
    PostgresRuntimeProviderSettingRepository,
)
from backend.app.repositories.postgres_scheduler_job_config_repository import (
    PostgresSchedulerJobConfigRepository,
)
from backend.app.repositories.postgres_site_contact_page_repository import (
    PostgresSiteContactPageRepository,
)
from backend.app.repositories.postgres_smtp_settings_repository import (
    PostgresSmtpSettingsRepository,
)
from backend.app.repositories.postgres_telegram_link_attempt_repository import (
    PostgresTelegramLinkAttemptRepository,
)
from backend.app.repositories.postgres_telegram_settings_repository import (
    PostgresTelegramSettingsRepository,
)
from backend.app.repositories.postgres_tracking_repository import PostgresTrackingRepository
from backend.app.repositories.postgres_ui_library_repository import PostgresUiLibraryRepository
from backend.app.repositories.postgres_user_account_repository import (
    PostgresUserAccountRepository,
)
from backend.app.repositories.postgres_user_subscription_repository import (
    PostgresUserSubscriptionRepository,
)
from backend.app.repositories.postgres_x_credentials_repository import (
    PostgresXCredentialRepository,
)
from backend.app.repositories.postgres_x_translation_repository import (
    PostgresXTranslationTaskRepository,
)
from backend.app.repositories.postgres_x_watch_repository import (
    PostgresXWatchAccountRepository,
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
    IngestionTaskWriter,
    LatestTaskByNameReader,
    LatestTaskReader,
    MonitorTaskRepository,
    RecentTaskReader,
    TaskByIdReader,
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


class ApplicationIngestionTaskRepository(
    IngestionTaskWriter,
    LatestTaskReader,
    LatestTaskByNameReader,
    TaskByIdReader,
    RecentTaskReader,
    MonitorTaskRepository,
    IngestionTaskAdminRepository,
):
    pass


@dataclass(frozen=True)
class ApplicationRepositories:
    ui_library: PostgresUiLibraryRepository
    users: UserAccountRepository
    oauth_identities: OAuthIdentityRepository
    orders: PaymentOrderRepository
    conversations: ConversationRepository
    attachments: AttachmentRepository
    documents: DocumentRepository
    ingestion_tasks: ApplicationIngestionTaskRepository
    rank_snapshots: RankSnapshotRepository
    briefings: BriefingContentRepository
    briefing_subscriptions: BriefingSubscriptionRepository
    evaluations: EvaluationRepository
    runtime_provider_settings: RuntimeProviderSettingRepository
    scheduler_job_configs: SchedulerJobConfigRepository
    smtp_settings: SmtpSettingsRepository
    payment_settings: PaymentSettingsRepository
    oauth_settings: OAuthSettingsRepository
    payment_plan_overrides: PaymentPlanOverridesRepository
    email_pool_settings: EmailPoolSettingsRepository
    site_contact_page: SiteContactPageRepository
    error_events: ErrorEventRepository
    mcp_server_configs: McpServerConfigRepository
    mcp_access_tokens: McpAccessTokenRepository
    feed_tokens: FeedTokenRepository
    github_ingestion: GitHubProjectIngestionRepository
    github_enrichment: GitHubProjectEnrichmentRepository
    tool_website_enrichment: ToolWebsiteEnrichmentRepository
    project_collections: UserProjectCollectionRepository
    project_recommendations: GitHubProjectRecommendationRepository
    github_semantic_sources: GitHubProjectSemanticSourceRepository
    x_credentials: XCredentialRepository
    x_translation_tasks: XTranslationTaskRepository
    x_watch_accounts: XWatchAccountRepository
    push_channels: PushChannelRepository
    user_subscriptions: UserSubscriptionRepository
    push_deliveries: PushDeliveryRepository
    telegram_link_attempts: TelegramLinkAttemptRepository
    telegram_settings: TelegramSettingsRepository
    tracking: PostgresTrackingRepository | None = None


def _env_x_watch_handles() -> tuple[str, ...]:
    """TWITTER_WATCH_HANDLES 的粗解析（逗号分隔）；仓储种子再做 @/小写归一。

    采集层刻意直接读 env（绕开 Settings @lru_cache 的测试脚注），此处沿用
    同一约定，保证种子列表与 XCrawler env 兜底读取一致。
    """
    raw = os.environ.get("TWITTER_WATCH_HANDLES", "")
    return tuple(part for piece in raw.split(",") if (part := piece.strip()))


def _env_x_credentials() -> tuple[str, str] | None:
    """读取旧部署的完整 cookie pair，仅作为空表首次 bootstrap 来源。"""
    auth_token = os.environ.get("TWITTER_AUTH_TOKEN", "").strip()
    ct0 = os.environ.get("TWITTER_CT0", "").strip()
    if not auth_token or not ct0:
        return None
    return auth_token, ct0


def create_application_repositories(
    *,
    postgres: PostgresDatabaseLifecycle,
) -> ApplicationRepositories:
    return ApplicationRepositories(
        ui_library=PostgresUiLibraryRepository(postgres),
        users=PostgresUserAccountRepository(postgres),
        oauth_identities=PostgresOAuthIdentityRepository(postgres),
        orders=PostgresPaymentOrderRepository(postgres),
        conversations=PostgresConversationRepository(postgres),
        attachments=PostgresAttachmentRepository(postgres),
        documents=PostgresDocumentRepository(postgres),
        ingestion_tasks=PostgresIngestionTaskRepository(postgres),
        rank_snapshots=PostgresRankSnapshotRepository(postgres),
        briefings=PostgresBriefingRepository(postgres),
        briefing_subscriptions=PostgresBriefingSubscriptionRepository(postgres),
        evaluations=PostgresEvaluationRepository(postgres),
        runtime_provider_settings=PostgresRuntimeProviderSettingRepository(postgres),
        scheduler_job_configs=PostgresSchedulerJobConfigRepository(postgres),
        smtp_settings=PostgresSmtpSettingsRepository(postgres),
        payment_settings=PostgresPaymentSettingsRepository(postgres),
        oauth_settings=PostgresOAuthSettingsRepository(postgres),
        payment_plan_overrides=PostgresPaymentPlanOverridesRepository(postgres),
        email_pool_settings=PostgresEmailPoolSettingsRepository(postgres),
        site_contact_page=PostgresSiteContactPageRepository(postgres),
        error_events=PostgresErrorEventRepository(postgres),
        mcp_server_configs=PostgresMcpServerConfigRepository(postgres),
        mcp_access_tokens=PostgresMcpAccessTokenRepository(postgres),
        feed_tokens=PostgresFeedTokenRepository(postgres),
        github_ingestion=PostgresGitHubProjectIngestionRepository(postgres),
        github_enrichment=PostgresGitHubProjectEnrichmentRepository(postgres),
        tool_website_enrichment=PostgresToolWebsiteEnrichmentRepository(postgres),
        project_collections=PostgresProjectWriteRepository(postgres),
        project_recommendations=PostgresProjectWriteRepository(postgres),
        github_semantic_sources=PostgresGitHubProjectSemanticSourceRepository(postgres),
        x_credentials=PostgresXCredentialRepository(
            postgres,
            bootstrap=_env_x_credentials(),
        ),
        x_translation_tasks=PostgresXTranslationTaskRepository(postgres),
        x_watch_accounts=PostgresXWatchAccountRepository(
            postgres,
            defaults=_env_x_watch_handles(),
        ),
        push_channels=PostgresPushChannelRepository(postgres),
        user_subscriptions=PostgresUserSubscriptionRepository(postgres),
        push_deliveries=PostgresPushDeliveryRepository(postgres),
        telegram_link_attempts=PostgresTelegramLinkAttemptRepository(postgres),
        telegram_settings=PostgresTelegramSettingsRepository(postgres),
        tracking=PostgresTrackingRepository(postgres),
    )
