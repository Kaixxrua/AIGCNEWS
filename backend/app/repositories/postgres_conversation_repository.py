from __future__ import annotations

import json
from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle


def _json_dumps(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def _json_loads_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        result = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return result if isinstance(result, list) else []


def _deserialize_message(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["sources"] = _json_loads_list(item.get("sources_json"))
    item["attachments"] = _json_loads_list(item.get("attachments_json"))
    item["thinking_preview"] = (item.get("thinking") or "")[:80]
    item["has_thinking"] = bool(item.get("thinking"))
    item["is_thinking"] = False
    item["is_streaming"] = item.get("status") == "streaming"
    return item


class PostgresConversationRepository:
    """Owner-scoped, lifecycle-backed conversation and message persistence."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def get_owned_conversation_context(
        self,
        *,
        user_id: int,
        conversation_id: int,
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                conversation = self._get_owned_conversation(
                    cursor,
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
                if conversation is None:
                    return None
                self._touch_conversation(cursor, conversation_id)
                messages = self._list_messages(cursor, conversation_id)
                conversation = self._get_owned_conversation(
                    cursor,
                    user_id=user_id,
                    conversation_id=conversation_id,
                ) or conversation
                return {"conversation": conversation, "messages": messages}

    def list_conversations(
        self,
        *,
        user_id: int,
        scope: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        offset = max(page - 1, 0) * page_size
        conditions = ["user_id = %s"]
        params: list[Any] = [user_id]
        if scope:
            conditions.append("scope = %s")
            params.append(scope)
        where_clause = " AND ".join(conditions)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT COUNT(*) AS cnt FROM conversations WHERE {where_clause}",
                    tuple(params),
                )
                total_row = cursor.fetchone()
                cursor.execute(
                    f"""
                    SELECT * FROM conversations
                    WHERE {where_clause}
                    ORDER BY last_accessed_at DESC, updated_at DESC, id DESC
                    LIMIT %s OFFSET %s
                    """,
                    tuple(params + [page_size, offset]),
                )
                rows = cursor.fetchall()
        return {
            "items": list(rows),
            "total": int(total_row["cnt"] if total_row else 0),
            "page": page,
            "page_size": page_size,
        }

    def ensure_conversation(
        self,
        *,
        user_id: int,
        scope: str = "global",
        scope_key: str | None = None,
        title: str | None = None,
        keep_latest: int = 10,
    ) -> dict[str, Any]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                conversation = self._ensure_conversation(
                    cursor,
                    user_id=user_id,
                    scope=scope,
                    scope_key=scope_key,
                    title=title,
                )
                self._touch_conversation(cursor, int(conversation["id"]))
                self._trim_user_conversations(cursor, user_id, keep_latest)
                return self._get_owned_conversation(
                    cursor,
                    user_id=user_id,
                    conversation_id=int(conversation["id"]),
                ) or conversation

    def create_conversation(
        self,
        *,
        user_id: int,
        scope: str = "global",
        scope_key: str | None = None,
        title: str | None = None,
        keep_latest: int = 10,
    ) -> dict[str, Any]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                conversation = self._create_conversation(
                    cursor,
                    user_id=user_id,
                    scope=scope,
                    scope_key=scope_key,
                    title=title,
                )
                self._touch_conversation(cursor, int(conversation["id"]))
                self._trim_user_conversations(cursor, user_id, keep_latest)
                return self._get_owned_conversation(
                    cursor,
                    user_id=user_id,
                    conversation_id=int(conversation["id"]),
                ) or conversation

    def delete_owned_conversation(
        self,
        *,
        user_id: int,
        conversation_id: int,
    ) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM conversations WHERE id = %s AND user_id = %s FOR UPDATE",
                    (conversation_id, user_id),
                )
                if cursor.fetchone() is None:
                    return False
                cursor.execute(
                    "DELETE FROM chat_messages WHERE conversation_id = %s",
                    (conversation_id,),
                )
                cursor.execute(
                    "DELETE FROM conversations WHERE id = %s AND user_id = %s",
                    (conversation_id, user_id),
                )
                return cursor.rowcount > 0

    def append_message_pair(
        self,
        *,
        user_id: int,
        conversation_id: int | None,
        scope: str,
        scope_key: str | None,
        user_message: str,
        assistant_content: str,
        assistant_thinking: str = "",
        sources: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        parent_message_id: int | None = None,
        title: str | None = None,
        max_messages: int = 10,
        max_conversations: int = 10,
    ) -> dict[str, Any]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                conversation = self._ensure_conversation(
                    cursor,
                    user_id=user_id,
                    scope=scope,
                    scope_key=scope_key,
                    title=title,
                )
                if conversation_id:
                    selected = self._get_owned_conversation(
                        cursor,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        for_update=True,
                    )
                    if selected is not None:
                        conversation = selected
                active_id = int(conversation["id"])
                self._touch_conversation(cursor, active_id)
                if parent_message_id is not None:
                    cursor.execute(
                        """
                        SELECT m.id
                        FROM chat_messages m
                        JOIN conversations c ON c.id = m.conversation_id
                        WHERE m.id = %s AND m.conversation_id = %s AND c.user_id = %s
                        FOR UPDATE
                        """,
                        (parent_message_id, active_id, user_id),
                    )
                    if cursor.fetchone() is None:
                        raise ValueError("message_not_found")
                user_row = self._create_message(
                    cursor,
                    conversation_id=active_id,
                    role="user",
                    content=user_message,
                    thinking="",
                    sources=[],
                    attachments=attachments or [],
                    status="done",
                    parent_message_id=parent_message_id,
                )
                assistant_row = self._create_message(
                    cursor,
                    conversation_id=active_id,
                    role="assistant",
                    content=assistant_content,
                    thinking=assistant_thinking,
                    sources=sources or [],
                    attachments=attachments or [],
                    status="done",
                    parent_message_id=int(user_row["id"]),
                )
                self._refresh_stats(
                    cursor,
                    active_id,
                    title=conversation.get("title") or title,
                    last_message_preview=(assistant_content or user_message).strip().replace("\n", " ")[:200],
                )
                self._trim_messages(cursor, active_id, max_messages)
                self._refresh_stats(cursor, active_id)
                self._trim_user_conversations(cursor, user_id, max_conversations)
                latest_conversation = self._get_owned_conversation(
                    cursor,
                    user_id=user_id,
                    conversation_id=active_id,
                ) or conversation
                return {
                    "conversation": latest_conversation,
                    "user_message": user_row,
                    "assistant_message": assistant_row,
                    "messages": self._list_messages(cursor, active_id),
                }

    def delete_owned_message_branch(
        self,
        *,
        user_id: int,
        message_id: int,
    ) -> dict[str, Any] | None:
        return self._delete_owned_suffix(
            user_id=user_id,
            message_id=message_id,
            include_target=True,
            include_target_row=False,
        )

    def prepare_owned_regeneration(
        self,
        *,
        user_id: int,
        message_id: int,
    ) -> dict[str, Any] | None:
        return self._delete_owned_suffix(
            user_id=user_id,
            message_id=message_id,
            include_target=True,
            include_target_row=True,
        )

    def count_user_messages_today(self, user_id: int) -> int:
        today_sql = """
            SELECT COUNT(*) AS cnt
            FROM chat_messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE c.user_id = %s
              AND m.role = 'user'
              AND (m.created_at AT TIME ZONE 'Asia/Shanghai')::date =
                  (CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai')::date
        """
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(today_sql, (user_id,))
                row = cursor.fetchone()
        return int(row["cnt"] if row else 0)

    def cleanup_stale_conversations(
        self,
        *,
        stale_days: int = 7,
        limit: int = 5,
    ) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id FROM conversations
                    WHERE last_accessed_at < CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')
                    ORDER BY last_accessed_at ASC, updated_at ASC, id ASC
                    LIMIT %s
                    FOR UPDATE
                    """,
                    (stale_days, limit),
                )
                delete_ids = [int(row["id"]) for row in cursor.fetchall()]
                if not delete_ids:
                    return 0
                placeholders = ", ".join(["%s"] * len(delete_ids))
                cursor.execute(
                    f"DELETE FROM conversations WHERE id IN ({placeholders})",
                    tuple(delete_ids),
                )
                return cursor.rowcount

    def _delete_owned_suffix(
        self,
        *,
        user_id: int,
        message_id: int,
        include_target: bool,
        include_target_row: bool,
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT m.*
                    FROM chat_messages m
                    JOIN conversations c ON c.id = m.conversation_id
                    WHERE m.id = %s AND c.user_id = %s
                    FOR UPDATE
                    """,
                    (message_id, user_id),
                )
                target_raw = cursor.fetchone()
                if target_raw is None:
                    return None
                target = _deserialize_message(dict(target_raw))
                conversation_id = int(target["conversation_id"])
                operator = ">=" if include_target else ">"
                cursor.execute(
                    f"""
                    SELECT id FROM chat_messages
                    WHERE conversation_id = %s
                      AND (created_at > %s OR (created_at = %s AND id {operator} %s))
                    ORDER BY created_at ASC, id ASC
                    """,
                    (
                        conversation_id,
                        target["created_at"],
                        target["created_at"],
                        message_id,
                    ),
                )
                delete_ids = [int(row["id"]) for row in cursor.fetchall()]
                if delete_ids:
                    placeholders = ", ".join(["%s"] * len(delete_ids))
                    cursor.execute(
                        f"DELETE FROM chat_messages WHERE id IN ({placeholders})",
                        tuple(delete_ids),
                    )
                self._refresh_stats(cursor, conversation_id)
                self._touch_conversation(cursor, conversation_id)
                conversation = self._get_owned_conversation(
                    cursor,
                    user_id=user_id,
                    conversation_id=conversation_id,
                )
                result = {
                    "deleted_ids": delete_ids,
                    "conversation": conversation,
                    "messages": self._list_messages(cursor, conversation_id),
                }
                if include_target_row:
                    result["target_message"] = target
                return result

    @staticmethod
    def _get_owned_conversation(
        cursor: Any,
        *,
        user_id: int,
        conversation_id: int,
        for_update: bool = False,
    ) -> dict[str, Any] | None:
        suffix = " FOR UPDATE" if for_update else ""
        cursor.execute(
            f"SELECT * FROM conversations WHERE id = %s AND user_id = %s{suffix}",
            (conversation_id, user_id),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def _ensure_conversation(
        self,
        cursor: Any,
        *,
        user_id: int,
        scope: str,
        scope_key: str | None,
        title: str | None,
    ) -> dict[str, Any]:
        if scope_key:
            cursor.execute(
                """
                SELECT * FROM conversations
                WHERE user_id = %s AND scope = %s AND scope_key = %s
                ORDER BY id DESC LIMIT 1 FOR UPDATE
                """,
                (user_id, scope, scope_key),
            )
        else:
            cursor.execute(
                """
                SELECT * FROM conversations
                WHERE user_id = %s AND scope = %s AND scope_key IS NULL
                ORDER BY id DESC LIMIT 1 FOR UPDATE
                """,
                (user_id, scope),
            )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return self._create_conversation(
            cursor,
            user_id=user_id,
            scope=scope,
            scope_key=scope_key,
            title=title,
        )

    @staticmethod
    def _create_conversation(
        cursor: Any,
        *,
        user_id: int,
        scope: str,
        scope_key: str | None,
        title: str | None,
    ) -> dict[str, Any]:
        cursor.execute(
            """
            INSERT INTO conversations (
                user_id, scope, scope_key, title, last_message_preview,
                message_count, last_accessed_at, updated_at, created_at
            ) VALUES (%s, %s, %s, %s, '', 0, NOW(), NOW(), NOW())
            RETURNING *
            """,
            (user_id, scope, scope_key, title or "新对话"),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("PostgreSQL conversation insert did not return a row")
        return dict(row)

    @staticmethod
    def _touch_conversation(cursor: Any, conversation_id: int) -> None:
        cursor.execute(
            """
            UPDATE conversations
            SET last_accessed_at = NOW(), updated_at = NOW()
            WHERE id = %s
            """,
            (conversation_id,),
        )

    @staticmethod
    def _create_message(
        cursor: Any,
        *,
        conversation_id: int,
        role: str,
        content: str,
        thinking: str,
        sources: list[dict[str, Any]],
        attachments: list[dict[str, Any]],
        status: str,
        parent_message_id: int | None,
    ) -> dict[str, Any]:
        cursor.execute(
            """
            INSERT INTO chat_messages (
                conversation_id, role, content, thinking, sources_json,
                attachments_json, status, parent_message_id, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, NOW(), NOW())
            RETURNING *
            """,
            (
                conversation_id,
                role,
                content,
                thinking,
                _json_dumps(sources),
                _json_dumps(attachments),
                status,
                parent_message_id,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("PostgreSQL message insert did not return a row")
        return _deserialize_message(dict(row))

    @staticmethod
    def _list_messages(cursor: Any, conversation_id: int) -> list[dict[str, Any]]:
        cursor.execute(
            """
            SELECT * FROM chat_messages
            WHERE conversation_id = %s
            ORDER BY created_at ASC, id ASC
            """,
            (conversation_id,),
        )
        return [_deserialize_message(dict(row)) for row in cursor.fetchall()]

    @staticmethod
    def _refresh_stats(
        cursor: Any,
        conversation_id: int,
        *,
        title: str | None = None,
        last_message_preview: str | None = None,
    ) -> None:
        cursor.execute(
            "SELECT COUNT(*) AS cnt FROM chat_messages WHERE conversation_id = %s",
            (conversation_id,),
        )
        count_row = cursor.fetchone()
        message_count = int(count_row["cnt"] if count_row else 0)
        if last_message_preview is None:
            cursor.execute(
                """
                SELECT content FROM chat_messages
                WHERE conversation_id = %s
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (conversation_id,),
            )
            latest = cursor.fetchone()
            last_message_preview = (latest.get("content") or "")[:200] if latest else ""
        if title is None:
            cursor.execute(
                """
                SELECT content FROM chat_messages
                WHERE conversation_id = %s AND role = 'user'
                ORDER BY created_at ASC, id ASC LIMIT 1
                """,
                (conversation_id,),
            )
            first_user = cursor.fetchone()
            if first_user:
                title = (first_user.get("content") or "新对话")[:60]
        cursor.execute(
            """
            UPDATE conversations
            SET title = COALESCE(%s, title), last_message_preview = %s,
                message_count = %s, last_accessed_at = NOW(), updated_at = NOW()
            WHERE id = %s
            """,
            (title, last_message_preview or "", message_count, conversation_id),
        )

    @staticmethod
    def _trim_messages(cursor: Any, conversation_id: int, keep_latest: int) -> int:
        if keep_latest <= 0:
            return 0
        cursor.execute(
            "SELECT id FROM chat_messages WHERE conversation_id = %s ORDER BY created_at DESC, id DESC LIMIT %s",
            (conversation_id, keep_latest),
        )
        keep_ids = [int(row["id"]) for row in cursor.fetchall()]
        if keep_ids:
            placeholders = ", ".join(["%s"] * len(keep_ids))
            cursor.execute(
                f"DELETE FROM chat_messages WHERE conversation_id = %s AND id NOT IN ({placeholders})",
                tuple([conversation_id] + keep_ids),
            )
        else:
            cursor.execute(
                "DELETE FROM chat_messages WHERE conversation_id = %s",
                (conversation_id,),
            )
        return cursor.rowcount

    @staticmethod
    def _trim_user_conversations(cursor: Any, user_id: int, keep_latest: int) -> int:
        if keep_latest <= 0:
            return 0
        cursor.execute(
            "SELECT id FROM conversations WHERE user_id = %s ORDER BY last_accessed_at DESC, updated_at DESC, id DESC LIMIT %s",
            (user_id, keep_latest),
        )
        keep_ids = [int(row["id"]) for row in cursor.fetchall()]
        if keep_ids:
            placeholders = ", ".join(["%s"] * len(keep_ids))
            cursor.execute(
                f"DELETE FROM conversations WHERE user_id = %s AND id NOT IN ({placeholders})",
                tuple([user_id] + keep_ids),
            )
        else:
            cursor.execute("DELETE FROM conversations WHERE user_id = %s", (user_id,))
        return cursor.rowcount
