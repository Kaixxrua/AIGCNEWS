from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.app.core.database import DatabaseLifecycle


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


class MySQLMcpAccessTokenRepository:
    """MySQL persistence for inbound MCP access tokens."""

    def __init__(self, database: DatabaseLifecycle) -> None:
        self._database = database

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
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM users WHERE id = %s FOR UPDATE",
                    (int(user_id),),
                )
                if not cur.fetchone():
                    raise ValueError("user does not exist")
                cur.execute(
                    """
                    DELETE FROM user_mcp_tokens
                    WHERE user_id = %s AND revoked_at IS NOT NULL
                    """,
                    (int(user_id),),
                )
                cur.execute(
                    """
                    INSERT INTO user_mcp_tokens
                        (user_id, token_hash, token_hint, scopes_json, client_type, client_label, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        int(user_id),
                        token_hash,
                        token_hint,
                        json.dumps(
                            scopes,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                        client_type,
                        client_label,
                        expires_at,
                    ),
                )
                token_id = int(cur.lastrowid)
                cur.execute(
                    """
                    SELECT id, user_id, token_hint, scopes_json, client_type, client_label,
                           expires_at, revoked_at, deleted_at, created_at, last_used_at
                    FROM user_mcp_tokens WHERE id = %s AND user_id = %s
                    """,
                    (token_id, int(user_id)),
                )
                row = cur.fetchone() or {}
            return {
                "token_metadata": self._mcp_token_metadata(row),
                "replaced_count": 0,
            }

    def list_user_mcp_tokens(self, *, user_id: int) -> list[dict[str, Any]]:
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, user_id, token_hint, scopes_json, client_type, client_label,
                           expires_at, revoked_at, deleted_at, created_at, last_used_at
                    FROM user_mcp_tokens
                    WHERE user_id = %s AND revoked_at IS NULL AND deleted_at IS NULL
                    ORDER BY created_at DESC, id DESC
                    """,
                    (int(user_id),),
                )
                rows = cur.fetchall()
            return [self._mcp_token_metadata(dict(row)) for row in rows]

    def get_user_by_mcp_token_hash(
        self,
        token_hash: str,
    ) -> dict[str, Any] | None:
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT t.id AS token_id, t.user_id, t.scopes_json, t.expires_at,
                           t.revoked_at, t.deleted_at, u.email, u.role
                    FROM user_mcp_tokens t JOIN users u ON u.id = t.user_id
                    WHERE t.token_hash = %s AND t.revoked_at IS NULL AND t.deleted_at IS NULL
                      AND (t.expires_at IS NULL OR t.expires_at > UTC_TIMESTAMP())
                    LIMIT 1
                    """,
                    (token_hash,),
                )
                row = cur.fetchone()
                if row:
                    cur.execute(
                        """
                        UPDATE user_mcp_tokens SET last_used_at = UTC_TIMESTAMP()
                        WHERE id = %s AND (last_used_at IS NULL OR last_used_at < UTC_TIMESTAMP() - INTERVAL 5 MINUTE)
                        """,
                        (row["token_id"],),
                    )
            return self._mcp_token_metadata(dict(row)) if row else None

    def delete_user_mcp_token(self, *, user_id: int, token_id: int) -> bool:
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE user_mcp_tokens
                    SET revoked_at = COALESCE(revoked_at, UTC_TIMESTAMP()), deleted_at = UTC_TIMESTAMP()
                    WHERE id = %s AND user_id = %s AND deleted_at IS NULL
                    """,
                    (int(token_id), int(user_id)),
                )
                return cur.rowcount > 0
