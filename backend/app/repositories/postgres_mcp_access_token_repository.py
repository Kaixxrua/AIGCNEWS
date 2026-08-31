from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from backend.app.core.config import settings
from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.domain.wechat_secret_box import (
    WeChatSecretBox,
    WeChatSecretBoxError,
)

logger = logging.getLogger(__name__)

# DSH 向导签发 token 的用途标记：鉴权 lookup 不感知 purpose，
# 仅管理面（ensure/rotate）使用。
DSH_MCP_TOKEN_PURPOSE = "dsh"
GENERIC_MCP_TOKEN_PURPOSE = "generic"


class DshMcpTokenSecretError(Exception):
    """DSH MCP token 加解密失败或加密密钥配置不可用。"""


# 构造期 secret_box 缺省哨兵：未显式传入时按 settings 装配（与 feed token
# build_feed_token_secret_box 同口径），显式 None 表示"无加密盒"（测试缝）。
_SECRET_BOX_UNSET: Any = object()


def build_dsh_mcp_token_secret_box(*, config=settings) -> WeChatSecretBox | None:
    """构建 DSH MCP token 加密盒；未配置或密钥非法时返回 None（不阻塞启动）。

    返回 None 时 ensure/rotate 拒绝落库（绝不退化为明文存储），
    由调用处映射为 503。
    """
    key = getattr(config, "dsh_mcp_token_encryption_key", "")
    if not key:
        return None
    try:
        return WeChatSecretBox.from_urlsafe_base64(
            key,
            getattr(config, "dsh_mcp_token_encryption_key_version", "v1"),
        )
    except WeChatSecretBoxError as exc:
        logger.warning("DSH MCP token 加密密钥非法: %s", exc)
        return None


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
        secret_box: WeChatSecretBox | None = _SECRET_BOX_UNSET,
    ) -> None:
        self._database = database
        self._max_active_tokens = max(1, int(max_active_tokens))
        self._secret_box = (
            build_dsh_mcp_token_secret_box()
            if secret_box is _SECRET_BOX_UNSET
            else secret_box
        )

    def _unseal_dsh_token(self, stored: Any) -> str:
        if self._secret_box is None:
            raise DshMcpTokenSecretError("dsh mcp token 加密密钥未配置")
        if not isinstance(stored, str) or not stored.strip():
            raise DshMcpTokenSecretError("dsh mcp token 密文缺失或损坏")
        try:
            envelope = json.loads(stored)
        except ValueError as exc:
            raise DshMcpTokenSecretError("dsh mcp token 密文不是密封信封") from exc
        try:
            return self._secret_box.unseal(envelope)
        except WeChatSecretBoxError as exc:
            raise DshMcpTokenSecretError("dsh mcp token 解封失败") from exc

    @staticmethod
    def _mcp_token_metadata(row: dict[str, Any]) -> dict[str, Any]:
        item = dict(row)
        # 密封材料与摘要是库内字段，任何对外 metadata 都不得携带
        item.pop("token_encrypted", None)
        item.pop("token_hash", None)
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
            # 会员到期时间（0048）随 token→user JOIN 透出，供读取侧判定生效档位
            "membership_expires_at",
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
                        (user_id, token_hash, token_hint, scopes_json, client_type, client_label, expires_at, purpose)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
                        GENERIC_MCP_TOKEN_PURPOSE,
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
                           t.revoked_at, t.deleted_at, u.email, u.role, u.membership_tier,
                           u.membership_expires_at
                    FROM user_mcp_tokens t JOIN users u ON u.id = t.user_id
                    WHERE t.token_hash = %s AND t.revoked_at IS NULL AND t.deleted_at IS NULL
                      AND (t.expires_at IS NULL OR t.expires_at > CURRENT_TIMESTAMP)
                      AND u.disabled = FALSE
                    LIMIT 1
                    """,
                    (token_hash,),
                )
                row = cursor.fetchone()
                if not row:
                    return None

                metadata = self._mcp_token_metadata(dict(row))
                # 认证 lookup 不能沿用 metadata 展示层对坏 JSON 的容错：
                # malformed scopes 必须在 OptionalMcpUser 边界变成 401，
                # 且不能因为认证失败更新 last_used_at。
                try:
                    scopes = json.loads(row.get("scopes_json", ""))
                except (TypeError, json.JSONDecodeError):
                    scopes = None
                if not isinstance(scopes, list) or not all(
                    isinstance(scope, str) for scope in scopes
                ):
                    metadata["scopes"] = None
                    return metadata

                cursor.execute(
                    """
                    UPDATE user_mcp_tokens SET last_used_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                      AND (last_used_at IS NULL OR last_used_at < CURRENT_TIMESTAMP - INTERVAL '5 minutes')
                    """,
                    (row["token_id"],),
                )
                return metadata

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

    # ------------------------------------------------------------------ DSH

    def _insert_dsh_token(
        self,
        cursor: Any,
        *,
        user_id: int,
        token_hash: str,
        token_hint: str,
        token_encrypted: str,
        scopes: list[str],
        client_type: str,
        client_label: str,
    ) -> dict[str, Any]:
        cursor.execute(
            """
            INSERT INTO user_mcp_tokens
                (user_id, token_hash, token_hint, scopes_json, client_type,
                 client_label, expires_at, purpose, token_encrypted)
            VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s)
            RETURNING id, user_id, token_hint, scopes_json, client_type,
                      client_label, expires_at, revoked_at, deleted_at,
                      created_at, last_used_at, purpose, token_encrypted
            """,
            (
                int(user_id),
                token_hash,
                token_hint,
                json.dumps(scopes, ensure_ascii=False, separators=(",", ":")),
                client_type,
                client_label,
                DSH_MCP_TOKEN_PURPOSE,
                token_encrypted,
            ),
        )
        inserted = cursor.fetchone()
        if inserted is None:
            raise RuntimeError("PostgreSQL DSH MCP token insert did not return a row")
        return dict(inserted)

    def ensure_user_dsh_mcp_token(
        self,
        *,
        user_id: int,
        token_hash: str,
        token_hint: str,
        token_encrypted: str,
        scopes: list[str],
        client_type: str,
        client_label: str,
    ) -> dict[str, Any]:
        """返回用户唯一活跃 DSH token：有密封行则解密回显（reused），
        没有则创建（created）；只有历史 hash-only 行时返回
        recovery_required（不静默轮换仍在使用的旧 token）。

        用户行 FOR UPDATE 串行化 + 0064 partial unique index 保证并发
        ensure 只产生一行活跃密封 DSH token；ensure 永不吊销任何 token。
        """
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
                    SELECT id, user_id, token_hint, scopes_json, client_type,
                           client_label, expires_at, revoked_at, deleted_at,
                           created_at, last_used_at, purpose, token_encrypted
                    FROM user_mcp_tokens
                    WHERE user_id = %s AND purpose = %s
                      AND revoked_at IS NULL AND deleted_at IS NULL
                      AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
                    ORDER BY (token_encrypted IS NOT NULL) DESC,
                             created_at DESC, id DESC
                    """,
                    (int(user_id), DSH_MCP_TOKEN_PURPOSE),
                )
                rows = [dict(row) for row in cursor.fetchall()]
                sealed_rows = [row for row in rows if row.get("token_encrypted")]
                if sealed_rows:
                    row = sealed_rows[0]
                    return {
                        "status": "reused",
                        "token": self._unseal_dsh_token(row.get("token_encrypted")),
                        "token_metadata": self._mcp_token_metadata(row),
                    }
                if rows:
                    # legacy hash-only DSH 行：无法回显明文；交由用户显式 rotate
                    return {
                        "status": "recovery_required",
                        "legacy_count": len(rows),
                    }
                row = self._insert_dsh_token(
                    cursor,
                    user_id=user_id,
                    token_hash=token_hash,
                    token_hint=token_hint,
                    token_encrypted=token_encrypted,
                    scopes=scopes,
                    client_type=client_type,
                    client_label=client_label,
                )
                return {
                    "status": "created",
                    # 回环解密刚落库的信封，验证密钥往返一致后再外发
                    "token": self._unseal_dsh_token(row.get("token_encrypted")),
                    "token_metadata": self._mcp_token_metadata(row),
                }

    def rotate_user_dsh_mcp_token(
        self,
        *,
        user_id: int,
        token_hash: str,
        token_hint: str,
        token_encrypted: str,
        scopes: list[str],
        client_type: str,
        client_label: str,
    ) -> dict[str, Any]:
        """单事务吊销全部活跃 DSH token（含 legacy hash-only 行）并签发
        新密封 token；generic token 不受影响。revoked_count 为真实吊销数。"""
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
                    UPDATE user_mcp_tokens
                    SET revoked_at = COALESCE(revoked_at, CURRENT_TIMESTAMP),
                        deleted_at = CURRENT_TIMESTAMP
                    WHERE user_id = %s AND purpose = %s AND deleted_at IS NULL
                    """,
                    (int(user_id), DSH_MCP_TOKEN_PURPOSE),
                )
                revoked_count = cursor.rowcount
                row = self._insert_dsh_token(
                    cursor,
                    user_id=user_id,
                    token_hash=token_hash,
                    token_hint=token_hint,
                    token_encrypted=token_encrypted,
                    scopes=scopes,
                    client_type=client_type,
                    client_label=client_label,
                )
                return {
                    "status": "rotated",
                    "token": self._unseal_dsh_token(row.get("token_encrypted")),
                    "token_metadata": self._mcp_token_metadata(row),
                    "revoked_count": max(0, int(revoked_count)),
                }
