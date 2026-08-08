from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle


def _to_iso_string(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


class PostgresMcpAccessTokenRepository:
    """PostgreSQL persistence for inbound MCP access tokens.

    每用户活跃 token 封顶 ``max_active_tokens``（默认 20）：创建新 token 时
    在同一事务内软淘汰最旧的超额 token（revoked_at + deleted_at），
    ``replaced_count`` 返回真实淘汰数，防止单用户 token 无限累积。
    """

    def __init__(
        self,
        database: PostgresDatabaseLifecycle,
        max_active_tokens: int = 20,
    ) -> None:
        self._database = database
        self._max_active_tokens = max(1, int(max_active_tokens))

    @staticmethod
    def _mcp_token_metadata(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        try:
            item["scopes"] = json.loads(item.pop("scopes_json", "[]") or "[]")
        except (TypeError, json.JSONDecodeError):
            item["scopes"] = []
        for field in (
            "expires_at",
            "revoked_at",
            "deleted_at",
            "created_at",
            "last_used_at",
        ):
            item[field] = _to_iso_string(item.get(field))
        return item

    def create_user_mcp_token(
        self,
        *,
        user_id: int,
        token_hash: str,
        token_hint: str,
        scopes: list[str],
        client_type: str,
        client_label: str = "",
        expires_at: Any = None,
    ) -> dict[str, Any]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM users WHERE id = %s FOR UPDATE",
                    (int(user_id),),
                )
                if not cursor.fetchone():
                    raise ValueError("user does not exist")
                cursor.execute(
                    """
                    DELETE FROM user_mcp_tokens
                    WHERE user_id = %s AND revoked_at IS NOT NULL
                    """,
                    (int(user_id),),
                )
                cursor.execute(
                    """
                    INSERT INTO user_mcp_tokens
                        (user_id, token_hash, token_hint, scopes_json, client_type, client_label, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        int(user_id),
                        token_hash,
                        token_hint,
                        json.dumps(scopes, ensure_ascii=False, separators=(",", ":")),
                        client_type,
                        client_label,
                        expires_at,
                    ),
                )
                inserted = cursor.fetchone()
                if inserted is None:
                    raise RuntimeError("PostgreSQL MCP token insert did not return an id")
                token_id = int(inserted["id"])
                # 封顶淘汰：保留最新 max_active_tokens 个活跃 token，超额的
                # 最旧者同事务软删除；用户行已 FOR UPDATE，计数无并发漂移
                cursor.execute(
                    """
                    UPDATE user_mcp_tokens
                    SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP),
                        deleted_at = CURRENT_TIMESTAMP
                    WHERE user_id = %s
                      AND deleted_at IS NULL
                      AND id IN (
                          SELECT id FROM user_mcp_tokens
                          WHERE user_id = %s
                            AND revoked_at IS NULL
                            AND deleted_at IS NULL
                          ORDER BY created_at DESC, id DESC
                          OFFSET %s
                      )
                    """,
                    (int(user_id), int(user_id), self._max_active_tokens),
                )
                replaced_count = cursor.rowcount
                cursor.execute(
                    """
                    SELECT id, user_id, token_hint, scopes_json, client_type, client_label,
                           expires_at, revoked_at, deleted_at, created_at, last_used_at
                    FROM user_mcp_tokens WHERE id = %s AND user_id = %s
                    """,
                    (token_id, int(user_id)),
                )
                row = cursor.fetchone() or {}
                return {
                    "token_metadata": self._mcp_token_metadata(dict(row)),
                    "replaced_count": max(0, int(replaced_count)),
                }

    def list_user_mcp_tokens(self, *, user_id: int) -> list[dict[str, Any]]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, user_id, token_hint, scopes_json, client_type, client_label,
                           expires_at, revoked_at, deleted_at, created_at, last_used_at
                    FROM user_mcp_tokens
                    WHERE user_id = %s AND revoked_at IS NULL AND deleted_at IS NULL
                    ORDER BY created_at DESC, id DESC
                    """,
                    (int(user_id),),
                )
                return [
                    self._mcp_token_metadata(dict(row)) for row in cursor.fetchall()
                ]

    def get_user_by_mcp_token_hash(
        self,
        token_hash: str,
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT t.id AS token_id, t.user_id, t.scopes_json, t.expires_at,
                           t.revoked_at, t.deleted_at, u.email, u.role
                    FROM user_mcp_tokens t JOIN users u ON u.id = t.user_id
                    WHERE t.token_hash = %s AND t.revoked_at IS NULL AND t.deleted_at IS NULL
                      AND (t.expires_at IS NULL OR t.expires_at > CURRENT_TIMESTAMP)
                    LIMIT 1
                    """,
                    (token_hash,),
                )
                row = cursor.fetchone()
                if row:
                    cursor.execute(
                        """
                        UPDATE user_mcp_tokens SET last_used_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                          AND (last_used_at IS NULL OR last_used_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes')
                        """,
                        (row["token_id"],),
                    )
                return self._mcp_token_metadata(dict(row)) if row else None

    def delete_user_mcp_token(self, *, user_id: int, token_id: int) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE user_mcp_tokens
                    SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP),
                        deleted_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND user_id = %s AND deleted_at IS NULL
                    """,
                    (int(token_id), int(user_id)),
                )
                return cursor.rowcount > 0
