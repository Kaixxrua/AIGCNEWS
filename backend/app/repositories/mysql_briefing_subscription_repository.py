from __future__ import annotations

from typing import Any

from backend.app.core.database import DatabaseLifecycle


class MySQLBriefingSubscriptionRepository:
    """MySQL persistence for briefing subscriptions and delivery recipients."""

    def __init__(self, database: DatabaseLifecycle) -> None:
        self._database = database

    def upsert_briefing_subscription(
        self,
        user_id: int,
        email: str,
        source: str = "all",
        period: str = "daily",
    ) -> dict[str, Any]:
        """Create or reactivate a briefing subscription."""
        sql = """
            INSERT INTO briefing_subscriptions (user_id, email, source, period, is_active, updated_at)
            VALUES (%s, %s, %s, %s, 1, NOW())
            ON DUPLICATE KEY UPDATE
                email = VALUES(email),
                is_active = 1,
                updated_at = NOW()
        """
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (user_id, email, source, period))
                cur.execute(
                    "SELECT * FROM briefing_subscriptions WHERE user_id = %s AND source = %s AND period = %s",
                    (user_id, source, period),
                )
                row = cur.fetchone()
            return dict(row) if row else {}

    def cancel_briefing_subscription(
        self,
        user_id: int,
        source: str = "all",
        period: str = "daily",
    ) -> bool:
        """Soft-delete a briefing subscription."""
        sql = """
            UPDATE briefing_subscriptions
            SET is_active = 0, updated_at = NOW()
            WHERE user_id = %s AND source = %s AND period = %s
        """
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (user_id, source, period))
                affected = cur.rowcount
            return affected > 0

    def get_user_briefing_subscriptions(
        self,
        user_id: int,
    ) -> list[dict[str, Any]]:
        """Return a user's active briefing subscriptions."""
        sql = """
            SELECT id, source, period, is_active, created_at, updated_at
            FROM briefing_subscriptions
            WHERE user_id = %s AND is_active = 1
            ORDER BY created_at ASC
        """
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (user_id,))
                rows = cur.fetchall()
            conn.commit()
            return list(rows)

    def get_active_subscribers(
        self,
        source: str = "all",
        period: str = "daily",
    ) -> list[dict[str, Any]]:
        """Return active recipients for a briefing delivery."""
        sql = """
            SELECT bs.id, bs.user_id, bs.email, bs.source, bs.period
            FROM briefing_subscriptions bs
            WHERE bs.is_active = 1 AND bs.source = %s AND bs.period = %s
        """
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (source, period))
                rows = cur.fetchall()
            conn.commit()
            return list(rows)
