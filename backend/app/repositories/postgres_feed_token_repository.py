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


class FeedTokenSecretError(Exception):
    """Feed token 加解密失败或加密密钥配置不可用。"""


# 构造期 secret_box 缺省哨兵：未显式传入时按 settings 装配（与 X 凭证
# build_x_credential_secret_box 同口径），显式 None 表示"无加密盒"（测试缝）。
_SECRET_BOX_UNSET: Any = object()


def build_feed_token_secret_box(*, config=settings) -> WeChatSecretBox | None:
    """构建 feed token 加密盒；未配置或密钥非法时返回 None（不阻塞启动）。

    返回 None 时写侧拒绝落库（绝不退化为明文存储），读侧无法回显明文，
    由调用处映射为 503。
    """
    key = getattr(config, "feed_token_encryption_key", "")
    if not key:
        return None
    try:
        return WeChatSecretBox.from_urlsafe_base64(
            key,
            getattr(config, "feed_token_encryption_key_version", "v1"),
        )
    except WeChatSecretBoxError as exc:
        logger.warning("Feed token 加密密钥非法: %s", exc)
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


class PostgresFeedTokenRepository:
    """PostgreSQL persistence for member RSS feed tokens.

    与 MCP access token 是彻底分离的凭证域：每用户至多一个活跃 token
    （0061 partial unique index 强制），无 expires_at——访问控制完全靠
    请求时校验（revoked_at IS NULL + users.disabled = FALSE + 生效会员
    档位判定，档位逻辑在路由层）。token 明文以 AES-256-GCM 密封落库，
    供用户随时回显完整 RSS 链接；库里永不出现明文。
    """

    def __init__(
        self,
        database: PostgresDatabaseLifecycle,
        secret_box: WeChatSecretBox | None = _SECRET_BOX_UNSET,
    ) -> None:
        self._database = database
        self._secret_box = (
            build_feed_token_secret_box()
            if secret_box is _SECRET_BOX_UNSET
            else secret_box
        )

    def _unseal_token(self, stored: Any) -> str:
        if self._secret_box is None:
            raise FeedTokenSecretError("feed token 加密密钥未配置")
        if not isinstance(stored, str) or not stored.strip():
            raise FeedTokenSecretError("feed token 密文缺失或损坏")
        try:
            envelope = json.loads(stored)
        except ValueError as exc:
            raise FeedTokenSecretError("feed token 密文不是密封信封") from exc
        try:
            return self._secret_box.unseal(envelope)
        except WeChatSecretBoxError as exc:
            raise FeedTokenSecretError("feed token 解封失败") from exc

    def _feed_token_metadata(
        self,
        row: dict[str, Any],
        *,
        include_token: bool,
    ) -> dict[str, Any]:
        item = {
            "id": row.get("id"),
            "user_id": row.get("user_id"),
            "token_hint": row.get("token_hint"),
            "created": bool(row.get("_created", False)),
        }
        for field in ("created_at", "last_used_at", "revoked_at"):
            item[field] = _to_iso_string(row.get(field))
        if include_token:
            item["token"] = self._unseal_token(row.get("token_encrypted"))
        return item

    def get_or_create_feed_token(
        self,
        *,
        user_id: int,
        token_hash: str,
        token_hint: str,
        token_encrypted: str,
    ) -> dict[str, Any]:
        """返回用户唯一活跃 token；无则创建。

        GET 幂等：用户行 FOR UPDATE 串行化后，已持有活跃 token 直接返回
        （解密回显明文）——并发 GET 不得互相吊销，只有显式 rotate 才换发。
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
                    SELECT id, user_id, token_hint, token_encrypted,
                           created_at, last_used_at
                    FROM user_feed_tokens
                    WHERE user_id = %s AND revoked_at IS NULL
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """,
                    (int(user_id),),
                )
                row = cursor.fetchone()
                if row:
                    return self._feed_token_metadata(dict(row), include_token=True)
                cursor.execute(
                    """
                    INSERT INTO user_feed_tokens
                        (user_id, token_hash, token_hint, token_encrypted)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, user_id, token_hint, token_encrypted, created_at
                    """,
                    (int(user_id), token_hash, token_hint, token_encrypted),
                )
                inserted = cursor.fetchone()
                if inserted is None:
                    raise RuntimeError("PostgreSQL feed token insert did not return a row")
                inserted["_created"] = True
                return self._feed_token_metadata(dict(inserted), include_token=True)

    def rotate_feed_token(
        self,
        *,
        user_id: int,
        token_hash: str,
        token_hint: str,
        token_encrypted: str,
    ) -> dict[str, Any]:
        """单事务吊销旧 token + 签发新 token；revoked_count 返回真实吊销数。"""
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
                    UPDATE user_feed_tokens SET revoked_at = CURRENT_TIMESTAMP
                    WHERE user_id = %s AND revoked_at IS NULL
                    """,
                    (int(user_id),),
                )
                revoked_count = cursor.rowcount
                cursor.execute(
                    """
                    INSERT INTO user_feed_tokens
                        (user_id, token_hash, token_hint, token_encrypted)
                    VALUES (%s, %s, %s, %s)
                    RETURNING id, user_id, token_hint, token_encrypted, created_at
                    """,
                    (int(user_id), token_hash, token_hint, token_encrypted),
                )
                inserted = cursor.fetchone()
                if inserted is None:
                    raise RuntimeError("PostgreSQL feed token insert did not return a row")
                inserted["_created"] = True
                metadata = self._feed_token_metadata(dict(inserted), include_token=True)
                metadata["revoked_count"] = max(0, int(revoked_count))
                return metadata

    def get_user_by_feed_token_hash(
        self,
        token_hash: str,
    ) -> dict[str, Any] | None:
        """按 hash 解析 token 属主；吊销/禁用用户一律返回 None（fail-closed）。

        透出 membership_tier/membership_expires_at 供路由层判定生效档位。
        last_used_at 节流窗口 1 小时：RSS 阅读器轮询频率远高于 MCP 调用，
        更短的窗口（MCP 用 5 分钟）会造成不必要的写放大。
        """
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT t.id AS token_id, t.user_id, t.created_at, t.last_used_at,
                           u.email, u.role, u.membership_tier, u.membership_expires_at
                    FROM user_feed_tokens t JOIN users u ON u.id = t.user_id
                    WHERE t.token_hash = %s AND t.revoked_at IS NULL
                      AND u.disabled = FALSE
                    LIMIT 1
                    """,
                    (token_hash,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                cursor.execute(
                    """
                    UPDATE user_feed_tokens SET last_used_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                      AND (last_used_at IS NULL
                           OR last_used_at < CURRENT_TIMESTAMP - INTERVAL '1 hour')
                    """,
                    (row["token_id"],),
                )
                item = dict(row)
                for field in ("created_at", "last_used_at", "membership_expires_at"):
                    item[field] = _to_iso_string(item.get(field))
                return item
