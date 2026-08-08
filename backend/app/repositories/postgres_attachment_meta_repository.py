"""PostgreSQL persistence for chat attachment upload-session metadata.

Stores the ephemeral upload metadata previously kept in the in-memory
``_attachment_registry`` of ``attachment_service``. Rows are keyed by the
public attachment token (UUID string) so metadata survives process restarts
and is visible across workers.
"""

from __future__ import annotations

from typing import Any, Iterable

from backend.app.core.postgres_database import PostgresDatabaseLifecycle

_COLUMNS = (
    "attachment_id",
    "user_id",
    "attachment_type",
    "status",
    "file_name",
    "mime_type",
    "size_bytes",
    "page_count",
    "text_preview",
    "storage_path",
    "error_msg",
    "created_at",
    "expires_at",
)

_SELECT_COLUMNS = ", ".join(_COLUMNS)


class PostgresAttachmentMetaRepository:
    """Owner-scoped CRUD for chat_attachment_meta rows."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def upsert_attachment_meta(
        self,
        *,
        attachment_id: str,
        user_id: int,
        attachment_type: str,
        status: str,
        file_name: str = "",
        mime_type: str = "",
        size_bytes: int = 0,
        page_count: int = 0,
        text_preview: str = "",
        storage_path: str | None = None,
        error_msg: str = "",
        created_at: float,
        expires_at: float = 0.0,
    ) -> None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO chat_attachment_meta (
                        attachment_id,
                        user_id,
                        attachment_type,
                        status,
                        file_name,
                        mime_type,
                        size_bytes,
                        page_count,
                        text_preview,
                        storage_path,
                        error_msg,
                        created_at,
                        expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (attachment_id) DO UPDATE SET
                        user_id = EXCLUDED.user_id,
                        attachment_type = EXCLUDED.attachment_type,
                        status = EXCLUDED.status,
                        file_name = EXCLUDED.file_name,
                        mime_type = EXCLUDED.mime_type,
                        size_bytes = EXCLUDED.size_bytes,
                        page_count = EXCLUDED.page_count,
                        text_preview = EXCLUDED.text_preview,
                        storage_path = EXCLUDED.storage_path,
                        error_msg = EXCLUDED.error_msg,
                        created_at = EXCLUDED.created_at,
                        expires_at = EXCLUDED.expires_at
                    """,
                    (
                        attachment_id,
                        int(user_id),
                        attachment_type,
                        status,
                        file_name,
                        mime_type,
                        int(size_bytes),
                        int(page_count),
                        text_preview,
                        storage_path,
                        error_msg,
                        float(created_at),
                        float(expires_at),
                    ),
                )

    def get_attachment_meta(
        self,
        attachment_id: str,
        *,
        user_id: int | None = None,
    ) -> dict[str, Any] | None:
        sql = f"SELECT {_SELECT_COLUMNS} FROM chat_attachment_meta WHERE attachment_id = %s"
        params: list[Any] = [attachment_id]
        if user_id is not None:
            sql += " AND user_id = %s"
            params.append(int(user_id))
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, tuple(params))
                row = cursor.fetchone()
                return dict(row) if row else None

    def list_attachment_meta(
        self,
        attachment_ids: list[str],
        *,
        user_id: int,
    ) -> list[dict[str, Any]]:
        """Return owned rows in the requested order, preserving duplicates."""
        if not attachment_ids:
            return []
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {_SELECT_COLUMNS}
                    FROM chat_attachment_meta
                    WHERE attachment_id = ANY(%s) AND user_id = %s
                    """,
                    (list(attachment_ids), int(user_id)),
                )
                rows_by_id = {row["attachment_id"]: dict(row) for row in cursor.fetchall()}
        return [
            rows_by_id[attachment_id]
            for attachment_id in attachment_ids
            if attachment_id in rows_by_id
        ]

    def existing_attachment_ids(self, attachment_ids: Iterable[str]) -> set[str]:
        ids = list(attachment_ids)
        if not ids:
            return set()
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT attachment_id FROM chat_attachment_meta "
                    "WHERE attachment_id = ANY(%s)",
                    (ids,),
                )
                return {row["attachment_id"] for row in cursor.fetchall()}

    def delete_expired_attachment_meta(self, now_ts: float) -> int:
        """Delete rows past their TTL (expires_at > 0); returns removed count."""
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM chat_attachment_meta "
                    "WHERE expires_at > 0 AND expires_at < %s",
                    (float(now_ts),),
                )
                return int(cursor.rowcount or 0)
