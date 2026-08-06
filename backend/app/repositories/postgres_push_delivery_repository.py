from __future__ import annotations

from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.push_delivery_repository import PushDeliveryRepository

_DELIVERY_COLUMNS = """
    id, subscription_id, item_key, status, attempts, last_error,
    sent_at, created_at, updated_at
"""


class PostgresPushDeliveryRepository(PushDeliveryRepository):
    """PostgreSQL persistence for idempotent push delivery records."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def get_delivery(
        self,
        *,
        subscription_id: int,
        item_key: str,
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {_DELIVERY_COLUMNS}
                    FROM push_deliveries
                    WHERE subscription_id = %s AND item_key = %s
                    """,
                    (subscription_id, item_key),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def create_delivery(
        self,
        *,
        subscription_id: int,
        item_key: str,
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO push_deliveries (subscription_id, item_key)
                    VALUES (%s, %s)
                    ON CONFLICT (subscription_id, item_key) DO NOTHING
                    RETURNING {_DELIVERY_COLUMNS}
                    """,
                    (subscription_id, item_key),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def mark_delivery_sent(self, *, delivery_id: int, attempts: int) -> None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                # 并发派发下只允许从 pending 迁移到 sent，已 sent 的保持原状。
                cursor.execute(
                    """
                    UPDATE push_deliveries
                    SET status = 'sent',
                        attempts = %s,
                        last_error = NULL,
                        sent_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status = 'pending'
                    """,
                    (attempts, delivery_id),
                )

    def record_attempt_failed(
        self,
        *,
        delivery_id: int,
        attempts: int,
        last_error: str,
        exhausted: bool,
    ) -> None:
        status = "failed" if exhausted else "pending"
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE push_deliveries
                    SET status = %s,
                        attempts = %s,
                        last_error = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status = 'pending'
                    """,
                    (status, attempts, last_error[:2000], delivery_id),
                )
