from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

from psycopg import errors

from backend.app.core.config import settings
from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.domain.wechat_secret_box import (
    WeChatSecretBox,
    WeChatSecretBoxError,
)
from backend.app.repositories.mcp_server_repository import McpServerConfigConflictError

logger = logging.getLogger(__name__)

McpServerDefault = tuple[str, str, str]


class McpServerSecretError(Exception):
    """MCP Server auth_token 加解密失败或加密密钥配置不可用。"""


# 构造期 secret_box 缺省哨兵：未显式传入时按 settings 装配（与推送渠道
# build_push_channel_secret_box 同口径），显式 None 表示"无加密盒"（测试缝）。
_SECRET_BOX_UNSET: Any = object()

_ENVELOPE_KEYS = ("v", "ct", "nonce")


def _parse_sealed_envelope(value: Any) -> dict[str, str] | None:
    """识别密封信封字符串（box.seal 的 JSON 序列化）；非信封返回 None。

    历史明文 token 是纯字符串，永远不会解析成带 v/ct/nonce 的 JSON
    对象，因此形状识别即可区分新老数据，无需额外标记列。
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text.startswith("{"):
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    envelope = {key: data.get(key) for key in _ENVELOPE_KEYS}
    if any(not isinstance(item, str) or not item for item in envelope.values()):
        return None
    return envelope  # type: ignore[return-value]


def build_mcp_server_secret_box(*, config=settings) -> WeChatSecretBox | None:
    """构建 MCP Server 加密盒；未配置或密钥非法时返回 None（不阻塞启动）。

    返回 None 时使用处自行拒绝处理 secret（写侧不降级为明文；历史明文行
    仍可读），对齐微信/推送渠道密钥的装配策略。
    """
    key = config.mcp_server_encryption_key
    if not key:
        return None
    try:
        return WeChatSecretBox.from_urlsafe_base64(
            key,
            config.mcp_server_encryption_key_version,
        )
    except WeChatSecretBoxError as exc:
        logger.warning("MCP Server 加密密钥非法: %s", exc)
        return None


class PostgresMcpServerConfigRepository:
    """PostgreSQL persistence for internal MCP Server configuration rows.

    auth_token 以 AES-256-GCM 密封信封落库（复用 WeChatSecretBox，与 X 凭证
    池同一口径）：写入侧一律密封；读取侧识别信封并解密还原明文，历史明文
    行原样兼容（懒迁移：下次写入即密封）。读取方（后台投影、连接测试器）
    因此始终拿到明文，无需感知加密。密钥未配置时拒绝写入 secret，绝不
    降级为明文。
    """

    def __init__(
        self,
        database: PostgresDatabaseLifecycle,
        defaults: Sequence[McpServerDefault] = (),
        secret_box: WeChatSecretBox | None = _SECRET_BOX_UNSET,
    ) -> None:
        self._database = database
        self._defaults = tuple(defaults)
        self._secret_box = (
            build_mcp_server_secret_box()
            if secret_box is _SECRET_BOX_UNSET
            else secret_box
        )

    def _seal_for_write(self, plaintext: str) -> str:
        """密封待写入的 secret；密钥未配置时拒绝（不写明文）。"""
        if self._secret_box is None:
            raise McpServerSecretError(
                "MCP Server 加密密钥未配置，无法存储 auth_token"
            )
        envelope = self._secret_box.seal(plaintext)
        return json.dumps(envelope, ensure_ascii=False)

    def _carry_or_seal(self, stored: Any) -> str | None:
        """保留既有存储值：已密封的原样携带；历史明文立即密封迁移。"""
        if stored is None:
            return None
        if _parse_sealed_envelope(stored) is not None:
            return str(stored)
        plaintext = stored.strip() if isinstance(stored, str) else ""
        if not plaintext:
            return None
        return self._seal_for_write(plaintext)

    def _unseal_for_read(self, stored: Any) -> str | None:
        """读取侧还原明文：信封解密，历史明文原样返回。

        密钥缺失或解密失败（密钥轮换/数据损坏）时记告警并返回 None，该
        配置对下游表现为"未设置 token"，绝不把密文当明文外发。
        """
        if not isinstance(stored, str) or not stored.strip():
            return None
        value = stored.strip()
        envelope = _parse_sealed_envelope(value)
        if envelope is None:
            return value
        if self._secret_box is None:
            logger.warning("[McpServerConfigs] 加密密钥未配置，无法解密封存的 auth_token")
            return None
        try:
            return self._secret_box.unseal(envelope)
        except WeChatSecretBoxError as exc:
            logger.warning("[McpServerConfigs] auth_token 解密失败: %s", exc)
            return None

    def _project_row(self, row: dict[str, Any]) -> dict[str, Any]:
        projected = dict(row)
        projected["auth_token"] = self._unseal_for_read(row.get("auth_token"))
        return projected

    def _seed_default_mcp_server_configs(self) -> None:
        rows = [row for row in self._defaults if row[2].strip()]
        if not rows:
            return

        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                for server_key, display_name, url in rows:
                    cursor.execute(
                        """
                        INSERT INTO mcp_server_configs
                            (server_key, display_name, description, url, transport, auth_type, enabled)
                        VALUES (%s, %s, %s, %s, 'streamable_http', 'none', TRUE)
                        ON CONFLICT (server_key) DO NOTHING
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
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, server_key, display_name, description, url, transport,
                           auth_type, auth_token, enabled, last_test_status, last_test_message,
                           last_test_at, last_tools_json, created_at, updated_at
                    FROM mcp_server_configs
                    ORDER BY enabled DESC, display_name ASC, id ASC
                    """
                )
                return [self._project_row(row) for row in cursor.fetchall()]

    def get_mcp_server_config(self, server_id: int) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, server_key, display_name, description, url, transport,
                           auth_type, auth_token, enabled, last_test_status, last_test_message,
                           last_test_at, last_tools_json, created_at, updated_at
                    FROM mcp_server_configs
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (server_id,),
                )
                row = cursor.fetchone()
                return self._project_row(row) if row else None

    def _get_stored_row(self, server_id: int) -> dict[str, Any] | None:
        """读取未解密的原始行（更新路径保留既有信封时使用）。"""
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, server_key, display_name, description, url, transport,
                           auth_type, auth_token, enabled, last_test_status, last_test_message,
                           last_test_at, last_tools_json, created_at, updated_at
                    FROM mcp_server_configs
                    WHERE id = %s
                    LIMIT 1
                    """,
                    (server_id,),
                )
                row = cursor.fetchone()
                return dict(row) if row else None

    def create_mcp_server_config(self, payload: dict[str, Any]) -> dict[str, Any]:
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
        if auth_type == "none":
            clean_auth_token = None
        stored_auth_token = (
            self._seal_for_write(clean_auth_token) if clean_auth_token else None
        )

        try:
            with self._database.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO mcp_server_configs
                            (server_key, display_name, description, url, transport, auth_type, auth_token, enabled)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            server_key,
                            display_name,
                            description,
                            url,
                            transport,
                            auth_type,
                            stored_auth_token,
                            bool(payload.get("enabled", True)),
                        ),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise RuntimeError("PostgreSQL MCP server insert did not return an id")
                    server_id = int(row["id"])
        except errors.UniqueViolation as exc:
            if exc.diag.constraint_name == "uq_mcp_server_configs_key":
                raise McpServerConfigConflictError("server_key already exists") from exc
            raise

        row = self.get_mcp_server_config(server_id)
        return row or {}

    def update_mcp_server_config(
        self,
        server_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        existing = self._get_stored_row(server_id)
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
        if auth_type == "none" or bool(payload.get("clear_auth_token")):
            effective_auth_token: str | None = None
        elif clean_auth_token:
            effective_auth_token = self._seal_for_write(clean_auth_token)
        else:
            # 保留既有存储值：信封原样携带；历史明文立即密封迁移
            effective_auth_token = self._carry_or_seal(existing.get("auth_token"))
        enabled = bool(payload.get("enabled", bool(existing.get("enabled"))))

        try:
            with self._database.transaction() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
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
                            updated_at = CURRENT_TIMESTAMP
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
        except errors.UniqueViolation as exc:
            if exc.diag.constraint_name == "uq_mcp_server_configs_key":
                raise McpServerConfigConflictError("server_key already exists") from exc
            raise

        return self.get_mcp_server_config(server_id)

    def delete_mcp_server_config(self, server_id: int) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM mcp_server_configs WHERE id = %s",
                    (server_id,),
                )
                return cursor.rowcount > 0

    def update_mcp_server_test_result(
        self,
        server_id: int,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        status = (result.get("status") or "unknown").strip().lower()
        message = (result.get("message") or "").strip()
        tools = result.get("tools") or []
        tools_json = json.dumps(tools, ensure_ascii=False) if tools else "[]"
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE mcp_server_configs
                    SET last_test_status = %s,
                        last_test_message = %s,
                        last_test_at = CURRENT_TIMESTAMP,
                        last_tools_json = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (status, message, tools_json, server_id),
                )
                if cursor.rowcount <= 0:
                    return None
        return self.get_mcp_server_config(server_id)
