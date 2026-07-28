from __future__ import annotations

from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle


class PostgresBriefingSubscriptionRepository:
    """PostgreSQL persistence for briefing subscriptions and recipients."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def upsert_briefing_subscription(
        self,
        user_id: int,
        email: str,
        source: str = "all",
        period: str = "daily",
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
                    (user_id, email, source, period),
                )
                row = cursor.fetchone()
                return dict(row) if row else {}

    def cancel_briefing_subscription(
        self,
        user_id: int,
        source: str = "all",
        period: str = "daily",
    ) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE briefing_subscriptions
                    SET is_active = FALSE, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = %s AND source = %s AND period = %s
                    """,
                    (user_id, source, period),
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
            WHERE user_id = %s AND is_active = TRUE
            ORDER BY created_at ASC
            """,
            (user_id,),
        )

    def get_active_subscribers(
        self,
        source: str = "all",
        period: str = "daily",
    ) -> list[dict[str, Any]]:
        return self._fetchall(
            """
            SELECT bs.id, bs.user_id, bs.email, bs.source, bs.period
            FROM briefing_subscriptions bs
            WHERE bs.is_active = TRUE AND bs.source = %s AND bs.period = %s
            """,
            (source, period),
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
