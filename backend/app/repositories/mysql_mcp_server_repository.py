from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from backend.app.core.database import DatabaseLifecycle


McpServerDefault = tuple[str, str, str]


class MySQLMcpServerConfigRepository:
    """MySQL persistence for internal MCP Server configuration rows."""

    def __init__(
        self,
        database: DatabaseLifecycle,
        defaults: Sequence[McpServerDefault] = (),
    ) -> None:
        self._database = database
        self._defaults = tuple(defaults)

    def _seed_default_mcp_server_configs(self) -> None:
        rows = [row for row in self._defaults if row[2].strip()]
        if not rows:
            return

        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                for server_key, display_name, url in rows:
                    cur.execute(
                        """
                        INSERT IGNORE INTO mcp_server_configs
                            (server_key, display_name, description, url, transport, auth_type, enabled)
                        VALUES (%s, %s, %s, %s, 'streamable_http', 'none', 1)
                        """,
                        (
                            server_key,
                            display_name,
                            "由环境变量初始化的 MCP Server，可在本页继续编辑。",
                            url.strip(),
                        ),
                    )

    def list_mcp_server_configs(self) -> list[dict[str, Any]]:
        self._seed_default_mcp_server_configs()
        sql = """
            SELECT id, server_key, display_name, description, url, transport,
                   auth_type, auth_token, enabled, last_test_status, last_test_message,
                   last_test_at, last_tools_json, created_at, updated_at
            FROM mcp_server_configs
            ORDER BY enabled DESC, display_name ASC, id ASC
        """
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()
            conn.commit()
            return [dict(row) for row in rows]

    def get_mcp_server_config(
        self,
        server_id: int,
    ) -> dict[str, Any] | None:
        sql = """
            SELECT id, server_key, display_name, description, url, transport,
                   auth_type, auth_token, enabled, last_test_status, last_test_message,
                   last_test_at, last_tools_json, created_at, updated_at
            FROM mcp_server_configs
            WHERE id = %s
            LIMIT 1
        """
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (server_id,))
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None

    def create_mcp_server_config(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        server_key = (payload.get("server_key") or "").strip().lower()
        display_name = (payload.get("display_name") or "").strip()
        description = (payload.get("description") or "").strip()
        url = (payload.get("url") or "").strip()
        transport = (payload.get("transport") or "streamable_http").strip().lower()
        auth_type = (payload.get("auth_type") or "none").strip().lower()
        auth_token = payload.get("auth_token")
        clean_auth_token = (
            auth_token.strip()
            if isinstance(auth_token, str) and auth_token.strip()
            else None
        )
        enabled = 1 if payload.get("enabled", True) else 0
        if auth_type == "none":
            clean_auth_token = None

        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO mcp_server_configs
                        (server_key, display_name, description, url, transport, auth_type, auth_token, enabled)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        server_key,
                        display_name,
                        description,
                        url,
                        transport,
                        auth_type,
                        clean_auth_token,
                        enabled,
                    ),
                )
                server_id = int(cur.lastrowid)

        row = self.get_mcp_server_config(server_id)
        return row or {}

    def update_mcp_server_config(
        self,
        server_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        existing = self.get_mcp_server_config(server_id)
        if not existing:
            return None

        server_key = (
            payload.get("server_key") or existing.get("server_key") or ""
        ).strip().lower()
        display_name = (
            payload.get("display_name") or existing.get("display_name") or ""
        ).strip()
        description = (
            payload.get("description")
            if "description" in payload
            else existing.get("description")
        ) or ""
        description = str(description).strip()
        url = (payload.get("url") or existing.get("url") or "").strip()
        transport = (
            payload.get("transport")
            or existing.get("transport")
            or "streamable_http"
        ).strip().lower()
        auth_type = (
            payload.get("auth_type") or existing.get("auth_type") or "none"
        ).strip().lower()
        auth_token = payload.get("auth_token")
        clean_auth_token = (
            auth_token.strip()
            if isinstance(auth_token, str) and auth_token.strip()
            else None
        )
        clear_auth_token = bool(payload.get("clear_auth_token"))
        if auth_type == "none" or clear_auth_token:
            effective_auth_token: str | None = None
        elif clean_auth_token:
            effective_auth_token = clean_auth_token
        else:
            effective_auth_token = existing.get("auth_token")
        enabled = 1 if payload.get("enabled", bool(existing.get("enabled"))) else 0

        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE mcp_server_configs
                    SET server_key = %s,
                        display_name = %s,
                        description = %s,
                        url = %s,
                        transport = %s,
                        auth_type = %s,
                        auth_token = %s,
                        enabled = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        server_key,
                        display_name,
                        description,
                        url,
                        transport,
                        auth_type,
                        effective_auth_token,
                        enabled,
                        server_id,
                    ),
                )

        return self.get_mcp_server_config(server_id)

    def delete_mcp_server_config(self, server_id: int) -> bool:
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM mcp_server_configs WHERE id = %s",
                    (server_id,),
                )
                affected = cur.rowcount
            return affected > 0

    def update_mcp_server_test_result(
        self,
        server_id: int,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        status = (result.get("status") or "unknown").strip().lower()
        message = (result.get("message") or "").strip()
        tools = result.get("tools") or []
        tools_json = json.dumps(tools, ensure_ascii=False) if tools else "[]"
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE mcp_server_configs
                    SET last_test_status = %s,
                        last_test_message = %s,
                        last_test_at = NOW(),
                        last_tools_json = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (status, message, tools_json, server_id),
                )
                affected = cur.rowcount
            if affected <= 0:
                return None
        return self.get_mcp_server_config(server_id)
