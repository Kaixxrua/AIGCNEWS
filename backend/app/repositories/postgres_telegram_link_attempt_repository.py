from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.telegram_link_attempt_repository import (
    TelegramLinkAttemptRepository,
)


class PostgresTelegramLinkAttemptRepository(TelegramLinkAttemptRepository):
    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def create_attempt(self, *, attempt_id: UUID, user_id: int, nonce_hash: str, expires_at: datetime) -> dict[str, Any]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO telegram_link_attempts
                        (attempt_id, user_id, nonce_hash, expires_at)
                    VALUES (%s, %s, %s, %s)
                    RETURNING attempt_id, user_id, status, expires_at, created_at,
                              completed_at, channel_id
                    """,
                    (str(attempt_id), user_id, nonce_hash, expires_at),
                )
                return dict(cursor.fetchone())

    def get_attempt(self, *, user_id: int, attempt_id: UUID) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT attempt_id, user_id, status, expires_at, created_at,
                           completed_at, channel_id
                    FROM telegram_link_attempts
                    WHERE attempt_id = %s AND user_id = %s
                    LIMIT 1
                    """,
                    (str(attempt_id), user_id),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def consume_attempt(self, *, nonce_hash: str, chat_id: str) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE telegram_link_attempts
                    SET status = 'completed', completed_at = CURRENT_TIMESTAMP,
                        telegram_chat_id = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE nonce_hash = %s AND status = 'pending'
                      AND expires_at > CURRENT_TIMESTAMP
                    RETURNING attempt_id, user_id, status, expires_at, created_at,
                              completed_at, channel_id
                    """,
                    (chat_id, nonce_hash),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def attach_channel(self, *, attempt_id: UUID, channel_id: int) -> None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE telegram_link_attempts
                    SET channel_id = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE attempt_id = %s
                    """,
                    (channel_id, str(attempt_id)),
                )

