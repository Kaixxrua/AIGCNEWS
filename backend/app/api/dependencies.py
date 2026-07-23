from __future__ import annotations

from fastapi import Depends, Request

from backend.app.core.database import DatabaseLifecycle
from backend.app.repositories.mysql_briefing_repository import MySQLBriefingRepository
from backend.app.repositories.mysql_briefing_subscription_repository import (
    MySQLBriefingSubscriptionRepository,
)
from backend.app.repositories.mysql_document_repository import MySQLDocumentRepository
from backend.app.repositories.mysql_evaluation_repository import (
    MySQLEvaluationRepository,
)
from backend.app.repositories.mysql_ingestion_task_repository import (
    MySQLIngestionTaskRepository,
)
from backend.app.repositories.mysql_mcp_access_token_repository import (
    MySQLMcpAccessTokenRepository,
)
from backend.app.repositories.mysql_mcp_server_repository import (
    MySQLMcpServerConfigRepository,
)
from backend.app.repositories.mysql_rank_snapshot_repository import (
    MySQLRankSnapshotRepository,
)
from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.repositories.mysql_runtime_provider_repository import (
    MySQLRuntimeProviderSettingRepository,
)
from backend.app.repositories.mysql_user_account_repository import (
    MySQLUserAccountRepository,
)


def get_database(request: Request) -> DatabaseLifecycle:
    """Return the database lifecycle configured by the application lifespan."""
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise RuntimeError("Database lifecycle is not configured")
    return database


def get_mysql_repository(
    database: DatabaseLifecycle = Depends(get_database),
) -> MySQLRepository:
    """Build the compatibility repository with the application-owned lifecycle."""
    return MySQLRepository(database=database)


def get_ingestion_task_repository(
    database: DatabaseLifecycle = Depends(get_database),
) -> MySQLIngestionTaskRepository:
    """Return task persistence while preserving compatibility schema setup."""
    return MySQLRepository(database=database).ingestion_tasks


def get_briefing_repository(
    database: DatabaseLifecycle = Depends(get_database),
) -> MySQLBriefingRepository:
    """Return briefing persistence while preserving compatibility schema setup."""
    return MySQLRepository(database=database).briefings


def get_briefing_subscription_repository(
    database: DatabaseLifecycle = Depends(get_database),
) -> MySQLBriefingSubscriptionRepository:
    """Return user subscription persistence through the compatibility facade."""
    return MySQLRepository(database=database).briefing_subscriptions


def get_evaluation_repository(
    database: DatabaseLifecycle = Depends(get_database),
) -> MySQLEvaluationRepository:
    """Return RAG evaluation persistence through the compatibility facade."""
    return MySQLRepository(database=database).evaluations


def get_mcp_server_config_repository(
    database: DatabaseLifecycle = Depends(get_database),
) -> MySQLMcpServerConfigRepository:
    """Return MCP Server configuration through the compatibility facade."""
    return MySQLRepository(database=database).mcp_server_configs


def get_mcp_access_token_repository(
    database: DatabaseLifecycle = Depends(get_database),
) -> MySQLMcpAccessTokenRepository:
    """Return MCP access-token persistence through the compatibility facade."""
    return MySQLRepository(database=database).mcp_access_tokens


def get_user_account_repository(
    database: DatabaseLifecycle = Depends(get_database),
) -> MySQLUserAccountRepository:
    """Return user account persistence through the compatibility facade."""
    return MySQLRepository(database=database).user_accounts


def get_runtime_provider_setting_repository(
    database: DatabaseLifecycle = Depends(get_database),
) -> MySQLRuntimeProviderSettingRepository:
    """Return runtime model configuration through the compatibility facade."""
    return MySQLRepository(database=database).runtime_provider_settings


def get_document_repository(
    database: DatabaseLifecycle = Depends(get_database),
) -> MySQLDocumentRepository:
    """Return document persistence through the compatibility facade."""
    return MySQLRepository(database=database).documents


def get_rank_snapshot_repository(
    database: DatabaseLifecycle = Depends(get_database),
) -> MySQLRankSnapshotRepository:
    """Return document rank snapshots through the compatibility facade."""
    return MySQLRepository(database=database).rank_snapshots
