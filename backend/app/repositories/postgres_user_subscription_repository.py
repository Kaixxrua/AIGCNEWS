from __future__ import annotations

from typing import Any

from psycopg import errors

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.user_subscription_repository import (
    UserSubscriptionRepository,
)

_SUBSCRIPTION_COLUMNS = """
    id, user_id, channel_id, source, frequency, status, created_at, updated_at
"""


class SubscriptionChannelMissingError(Exception):
    """Raised when a subscription insert violates the channel foreign key."""


class PostgresUserSubscriptionRepository(UserSubscriptionRepository):
    """PostgreSQL persistence for per-user subscriptions."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def create_subscription(
        self,
        *,
        user_id: int,
        channel_id: int,
        source: str,
        frequency: str,
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                try:
                    cursor.execute(
                        f"""
                        INSERT INTO user_subscriptions
                            (user_id, channel_id, source, frequency)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (user_id, channel_id, source, frequency) DO NOTHING
                        RETURNING {_SUBSCRIPTION_COLUMNS}
                        """,
                        (user_id, channel_id, source, frequency),
                    )
                except errors.ForeignKeyViolation as exc:
                    # 渠道在校验与插入之间被删除；服务层映射为领域 404。
                    raise SubscriptionChannelMissingError(
                        f"push channel {channel_id} does not exist"
                    ) from exc
                row = cursor.fetchone()
                return dict(row) if row else None

    def list_subscriptions(self, user_id: int) -> list[dict[str, Any]]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        s.id, s.user_id, s.channel_id, s.source, s.frequency,
                        s.status, s.created_at, s.updated_at,
                        c.channel_type, c.target
                    FROM user_subscriptions s
                    JOIN push_channels c ON c.id = s.channel_id
                    WHERE s.user_id = %s
                    ORDER BY s.id ASC
                    """,
                    (user_id,),
                )
                return [dict(row) for row in cursor.fetchall()]

    def set_subscription_status(
        self,
        *,
        user_id: int,
        subscription_id: int,
        status: str,
    ) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE user_subscriptions
                    SET status = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = %s AND id = %s
                    """,
                    (status, user_id, subscription_id),
                )
                return cursor.rowcount > 0

    def delete_subscription(self, *, user_id: int, subscription_id: int) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM user_subscriptions
                    WHERE user_id = %s AND id = %s
                    """,
                    (user_id, subscription_id),
                )
                return cursor.rowcount > 0
