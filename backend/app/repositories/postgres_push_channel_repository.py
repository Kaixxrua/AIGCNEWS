from __future__ import annotations

from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.push_channel_repository import PushChannelRepository

_CHANNEL_COLUMNS = """
    id, user_id, channel_type, target, encrypted_config, provider_key,
    display_target, verified, status, created_at, updated_at
"""


class PostgresPushChannelRepository(PushChannelRepository):
    """PostgreSQL persistence for per-user push channels."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def create_channel(
        self,
        *,
        user_id: int,
        channel_type: str,
        target: str,
        encrypted_config: str | None,
        verified: bool = False,
        provider_key: str | None = None,
        display_target: str | None = None,
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO push_channels
                        (user_id, channel_type, target, encrypted_config, verified,
                         provider_key, display_target)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    RETURNING {_CHANNEL_COLUMNS}
                    """,
                    (user_id, channel_type, target, encrypted_config, verified,
                     provider_key, display_target),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def find_channel_by_target(
        self,
        *,
        user_id: int,
        channel_type: str,
        target: str,
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {_CHANNEL_COLUMNS}
                    FROM push_channels
                    WHERE user_id = %s AND channel_type = %s AND target = %s
                    LIMIT 1
                    """,
                    (user_id, channel_type, target),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def find_channel_by_provider_key(
        self,
        *,
        channel_type: str,
        provider_key: str,
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {_CHANNEL_COLUMNS}
                    FROM push_channels
                    WHERE channel_type = %s AND provider_key = %s
                    LIMIT 1
                    """,
                    (channel_type, provider_key),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def get_channel(self, *, user_id: int, channel_id: int) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {_CHANNEL_COLUMNS}
                    FROM push_channels
                    WHERE user_id = %s AND id = %s
                    LIMIT 1
                    """,
                    (user_id, channel_id),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def list_channels(self, user_id: int) -> list[dict[str, Any]]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {_CHANNEL_COLUMNS}
                    FROM push_channels
                    WHERE user_id = %s
                    ORDER BY id ASC
                    """,
                    (user_id,),
                )
                return [dict(row) for row in cursor.fetchall()]

    def mark_channel_verified(self, *, user_id: int, channel_id: int) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE push_channels
                    SET verified = TRUE, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = %s AND id = %s
                    """,
                    (user_id, channel_id),
                )
                return cursor.rowcount > 0

    def set_channel_status(self, *, user_id: int, channel_id: int, status: str) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE push_channels
                    SET status = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE user_id = %s AND id = %s
                    """,
                    (status, user_id, channel_id),
                )
                return cursor.rowcount > 0

    def delete_channel(self, *, user_id: int, channel_id: int) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM push_channels
                    WHERE user_id = %s AND id = %s
                    """,
                    (user_id, channel_id),
                )
                return cursor.rowcount > 0
