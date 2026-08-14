from __future__ import annotations

import json
from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.email_pool_settings_repository import EmailPoolSettings

_COLUMNS = "entries, updated_at"


class PostgresEmailPoolSettingsRepository:
    """PostgreSQL persistence for the singleton email pool settings row (id = 1)."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def get_email_pool_settings(self) -> EmailPoolSettings | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {_COLUMNS}
                    FROM email_pool_settings
                    WHERE id = 1
                    """
                )
                row = cursor.fetchone()
                return self._row_to_settings(row) if row else None

    def upsert_email_pool_settings(self, *, entries_json: str) -> EmailPoolSettings:
        clean_entries = (entries_json or "").strip()
        # 写入侧纵深校验：服务层已校验，这里兜底保证落库内容恒为 JSON 数组
        if clean_entries:
            try:
                payload = json.loads(clean_entries)
            except ValueError as exc:
                raise ValueError("entries 必须是合法 JSON 数组") from exc
            if not isinstance(payload, list):
                raise ValueError("entries 必须是合法 JSON 数组")

        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO email_pool_settings
                        (id, entries, updated_at)
                    VALUES (1, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET
                        entries = EXCLUDED.entries,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING {_COLUMNS}
                    """,
                    (clean_entries,),
                )
                row = cursor.fetchone()

        return self._row_to_settings(row)

    def delete_email_pool_settings(self) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM email_pool_settings WHERE id = 1")
                return int(cursor.rowcount)

    def _row_to_settings(self, row: dict[str, Any]) -> EmailPoolSettings:
        return EmailPoolSettings(
            entries_json=str(row["entries"]),
            updated_at=row["updated_at"],
        )
