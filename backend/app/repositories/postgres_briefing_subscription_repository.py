from __future__ import annotations

from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle

# 简报仅按日生成；period 列保留在表结构中，统一写 'daily'。
_DAILY_PERIOD = "daily"


class PostgresBriefingSubscriptionRepository:
    """PostgreSQL persistence for briefing subscriptions and recipients."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def upsert_briefing_subscription(
        self,
        user_id: int,
        email: str,
        source: str = "all",
    ) -> dict[str, Any]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO briefing_subscriptions
                        (user_id, email, source, period, is_active, updated_at)
                    VALUES (%s, %s, %s, %s, TRUE, CURRENT_TIMESTAMP)
                    ON CONFLICT (user_id, source, period) DO UPDATE SET
                        email = EXCLUDED.email,
                        is_active = TRUE,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING *
                    """,
                    (user_id, email, source, _DAILY_PERIOD),
                )
                row = cursor.fetchone()
                return dict(row) if row else {}

    def cancel_briefing_subscription(
        self,
        user_id: int,
        source: str = "all",
    ) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE briefing_subscriptions
                    SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = %s AND source = %s AND period = %s
                    """,
                    (user_id, source, _DAILY_PERIOD),
                )
                return cursor.rowcount > 0

    def get_user_briefing_subscriptions(
        self,
        user_id: int,
    ) -> list[dict[str, Any]]:
        return self._fetchall(
            """
            SELECT id, source, period, is_active, created_at, updated_at
            FROM briefing_subscriptions
            WHERE user_id = %s AND is_active = TRUE AND period = %s
            ORDER BY created_at ASC
            """,
            (user_id, _DAILY_PERIOD),
        )

    def get_active_subscribers(
        self,
        source: str = "all",
    ) -> list[dict[str, Any]]:
        return self._fetchall(
            """
            SELECT bs.id, bs.user_id, bs.email, bs.source, bs.period,
                   bs.last_delivered_briefing_id
            FROM briefing_subscriptions bs
            WHERE bs.is_active = TRUE AND bs.source = %s AND bs.period = %s
            """,
            (source, _DAILY_PERIOD),
        )

    def mark_briefing_delivered(
        self,
        subscription_ids: list[int],
        briefing_id: int,
    ) -> None:
        if not subscription_ids:
            return
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE briefing_subscriptions
                    SET last_delivered_briefing_id = GREATEST(
                            COALESCE(last_delivered_briefing_id, -1), %s),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ANY(%s)
                    """,
                    (briefing_id, subscription_ids),
                )

    def _fetchall(
        self,
        sql: str,
        params: tuple[Any, ...],
    ) -> list[dict[str, Any]]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return [dict(row) for row in cursor.fetchall()]
