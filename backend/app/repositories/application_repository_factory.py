from __future__ import annotations

import os
from dataclasses import dataclass

from backend.app.core.config import settings
from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.domain.wechat_secret_box import (
    WeChatSecretBox,
    WeChatSecretBoxError,
)
from backend.app.repositories.attachment_repository import AttachmentRepository
from backend.app.repositories.briefing_repository import (
    BriefingContentRepository,
    BriefingSubscriptionRepository,
)
from backend.app.repositories.conversation_repository import ConversationRepository
from backend.app.repositories.document_repository import DocumentRepository
from backend.app.repositories.error_event_repository import ErrorEventRepository
from backend.app.repositories.evaluation_repository import EvaluationRepository
from backend.app.repositories.mcp_access_token_repository import (
    McpAccessTokenRepository,
)
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
from backend.app.repositories.postgres_error_event_repository import (
    PostgresErrorEventRepository,
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
from backend.app.repositories.postgres_smtp_settings_repository import (
    PostgresSmtpSettingsRepository,
)
from backend.app.repositories.postgres_user_account_repository import (
    PostgresUserAccountRepository,
)
from backend.app.repositories.postgres_user_subscription_repository import (
    PostgresUserSubscriptionRepository,
)
from backend.app.repositories.postgres_wechat_account_repository import (
    PostgresWeChatOfficialAccountRepository,
)
from backend.app.repositories.postgres_wechat_article_repository import (
    PostgresWeChatArticleRepository,
)
from backend.app.repositories.postgres_wechat_follow_repository import (
    PostgresWeChatFollowRepository,
)
from backend.app.repositories.postgres_wechat_session_repository import (
    PostgresWeChatSessionRepository,
)
from backend.app.repositories.postgres_x_credentials_repository import (
    PostgresXCredentialRepository,
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
from backend.app.repositories.smtp_settings_repository import SmtpSettingsRepository
from backend.app.repositories.task_repository import (
    IngestionTaskAdminRepository,
    IngestionTaskWriter,
    LatestTaskByNameReader,
    LatestTaskReader,
    MonitorTaskRepository,
    RecentTaskReader,
)
from backend.app.repositories.user_account_repository import UserAccountRepository
from backend.app.repositories.user_subscription_repository import (
    UserSubscriptionRepository,
)
from backend.app.repositories.wechat_account_repository import WeChatOfficialAccountRepository
from backend.app.repositories.wechat_article_repository import WeChatArticleRepository
from backend.app.repositories.wechat_follow_repository import WeChatFollowRepository
from backend.app.repositories.wechat_session_repository import (
    WeChatLoginAttemptRepository,
    WeChatSessionRepository,
)
from backend.app.repositories.x_credentials_repository import XCredentialRepository
from backend.app.repositories.x_watch_repository import XWatchAccountRepository


class ApplicationIngestionTaskRepository(
    IngestionTaskWriter,
    LatestTaskReader,
    LatestTaskByNameReader,
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
    scheduler_job_configs: SchedulerJobConfigRepository
    smtp_settings: SmtpSettingsRepository
    error_events: ErrorEventRepository
    mcp_server_configs: McpServerConfigRepository
    mcp_access_tokens: McpAccessTokenRepository
    github_ingestion: GitHubProjectIngestionRepository
    github_enrichment: GitHubProjectEnrichmentRepository
    tool_website_enrichment: ToolWebsiteEnrichmentRepository
    project_collections: UserProjectCollectionRepository
    project_recommendations: GitHubProjectRecommendationRepository
    github_semantic_sources: GitHubProjectSemanticSourceRepository
    x_credentials: XCredentialRepository
    x_watch_accounts: XWatchAccountRepository
    wechat_login_attempts: WeChatLoginAttemptRepository
    wechat_sessions: WeChatSessionRepository
    wechat_accounts: WeChatOfficialAccountRepository
    wechat_articles: WeChatArticleRepository
    wechat_follows: WeChatFollowRepository
    push_channels: PushChannelRepository
    user_subscriptions: UserSubscriptionRepository
    push_deliveries: PushDeliveryRepository


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


def _wechat_secret_box() -> WeChatSecretBox | None:
    """Build the configured WeChat secret box, returning None when not configured."""
    key = settings.wechat_session_encryption_key
    if not key:
        return None
    try:
        return WeChatSecretBox.from_urlsafe_base64(
            key,
            settings.wechat_session_encryption_key_version,
        )
    except WeChatSecretBoxError as exc:
        # Do not block application startup; WeChat endpoints will fail on use.
        import logging

        logging.getLogger(__name__).warning("WeChat encryption key invalid: %s", exc)
        return None


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
        scheduler_job_configs=PostgresSchedulerJobConfigRepository(postgres),
        smtp_settings=PostgresSmtpSettingsRepository(postgres),
        error_events=PostgresErrorEventRepository(postgres),
        mcp_server_configs=PostgresMcpServerConfigRepository(postgres),
        mcp_access_tokens=PostgresMcpAccessTokenRepository(postgres),
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
        x_watch_accounts=PostgresXWatchAccountRepository(
            postgres,
            defaults=_env_x_watch_handles(),
        ),
        wechat_login_attempts=PostgresWeChatSessionRepository(
            postgres,
            secret_box=_wechat_secret_box(),
        ),
        wechat_sessions=PostgresWeChatSessionRepository(
            postgres,
            secret_box=_wechat_secret_box(),
        ),
        wechat_accounts=PostgresWeChatOfficialAccountRepository(postgres),
        wechat_articles=PostgresWeChatArticleRepository(postgres),
        wechat_follows=PostgresWeChatFollowRepository(postgres),
        push_channels=PostgresPushChannelRepository(postgres),
        user_subscriptions=PostgresUserSubscriptionRepository(postgres),
        push_deliveries=PostgresPushDeliveryRepository(postgres),
    )
