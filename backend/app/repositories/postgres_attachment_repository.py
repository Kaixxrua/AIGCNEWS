from __future__ import annotations

import json
from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle


class PostgresAttachmentRepository:
    """PostgreSQL persistence for owner-scoped chat attachment metadata."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def create_chat_attachment(
        self,
        *,
        user_id: int,
        conversation_id: int | None,
        file_name: str,
        mime_type: str,
        modality: str,
        storage_path: str | None = None,
        file_size: int = 0,
        page_count: int | None = None,
        parse_status: str = "uploaded",
        extract_text: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO chat_attachments (
                        user_id,
                        conversation_id,
                        file_name,
                        mime_type,
                        modality,
                        storage_path,
                        file_size,
                        page_count,
                        parse_status,
                        extract_text,
                        meta_json,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    RETURNING *
                    """,
                    (
                        int(user_id),
                        conversation_id,
                        file_name,
                        mime_type,
                        modality,
                        storage_path,
                        int(file_size),
                        page_count,
                        parse_status,
                        extract_text,
                        json.dumps(meta or {}, ensure_ascii=False),
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("PostgreSQL attachment insert returned no row")
                return self._deserialize(dict(row))

    def get_chat_attachment(
        self,
        attachment_id: int,
        *,
        user_id: int | None = None,
    ) -> dict[str, Any] | None:
        sql = "SELECT * FROM chat_attachments WHERE id = %s"
        params: tuple[Any, ...] = (int(attachment_id),)
        if user_id is not None:
            sql += " AND user_id = %s"
            params += (int(user_id),)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return self._deserialize(dict(row)) if row else None

    def list_chat_attachments(
        self,
        *,
        user_id: int,
        conversation_id: int | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM chat_attachments WHERE user_id = %s"
        params: tuple[Any, ...] = (int(user_id),)
        if conversation_id is not None:
            sql += " AND conversation_id = %s"
            params += (int(conversation_id),)
        sql += " ORDER BY created_at DESC, id DESC"
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return [self._deserialize(dict(row)) for row in cursor.fetchall()]

    @staticmethod
    def _deserialize(row: dict[str, Any]) -> dict[str, Any]:
        raw_meta = row.get("meta_json")
        if isinstance(raw_meta, str):
            row["meta"] = json.loads(raw_meta or "{}")
        else:
            row["meta"] = raw_meta or {}
        return row
