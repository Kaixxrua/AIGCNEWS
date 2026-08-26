from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from backend.app.core.config import settings
from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.domain.wechat_secret_box import WeChatSecretBox, WeChatSecretBoxError
from backend.app.repositories.telegram_settings_repository import TelegramSettings

logger = logging.getLogger(__name__)

_SECRET_FIELDS = (
    ("bot_token", "bot_token_envelope"),
    ("webhook_secret", "webhook_secret_envelope"),
)
_COLUMNS = (
    "enabled, bot_token_envelope, bot_username, webhook_secret_envelope, "
    "link_ttl_seconds, request_timeout_seconds, updated_at"
)
_SECRET_BOX_UNSET: Any = object()


class TelegramSettingsSecretError(ValueError):
    """Telegram secrets must never be written without the deployment key."""


def build_telegram_settings_secret_box(*, config=settings) -> WeChatSecretBox | None:
    """构造 Telegram 配置 secret 的 AES-256-GCM envelope box。

    密钥解析顺序：TELEGRAM_CONFIG_ENCRYPTION_KEY 显式配置优先；未配置时回落
    复用 PUSH_CHANNEL_ENCRYPTION_KEY（同一 WeChatSecretBox 机制，推送渠道部署
    已就位，免去新增部署 env）。两者皆无 → None，写 secret 的路径 fail-closed。
    显式配置但非法 → None（不静默回落，避免运维误以为生效的是专用密钥）。
    """
    key = str(getattr(config, "telegram_config_encryption_key", "") or "")
    if key:
        try:
            return WeChatSecretBox.from_urlsafe_base64(
                key,
                str(getattr(config, "telegram_config_encryption_key_version", "v1")),
            )
        except WeChatSecretBoxError as exc:
            logger.warning("Telegram 配置加密密钥非法: %s", exc)
            return None
    fallback = str(getattr(config, "push_channel_encryption_key", "") or "")
    if not fallback:
        return None
    try:
        return WeChatSecretBox.from_urlsafe_base64(
            fallback,
            str(getattr(config, "push_channel_encryption_key_version", "v1")),
        )
    except WeChatSecretBoxError as exc:
        logger.warning("推送渠道加密密钥非法，Telegram secret 不可用: %s", exc)
        return None


def _parse_envelope(value: Any) -> dict[str, str] | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(parsed, dict) or set(parsed) != {"v", "ct", "nonce"}:
        return None
    if any(not isinstance(parsed[key], str) or not parsed[key] for key in parsed):
        return None
    return parsed


class PostgresTelegramSettingsRepository:
    """Singleton Telegram configuration with AES-GCM sealed secrets."""

    def __init__(
        self,
        database: PostgresDatabaseLifecycle,
        *,
        secret_box: WeChatSecretBox | None = _SECRET_BOX_UNSET,
    ) -> None:
        self._database = database
        self._secret_box = (
            build_telegram_settings_secret_box()
            if secret_box is _SECRET_BOX_UNSET
            else secret_box
        )

    def get_telegram_settings(self) -> TelegramSettings | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT {_COLUMNS} FROM telegram_settings WHERE id = 1")
                row = cursor.fetchone()
        return self._row_to_settings(row) if row else None

    def upsert_telegram_settings(
        self,
        *,
        enabled: bool,
        bot_token: str,
        bot_username: str,
        webhook_secret: str,
        link_ttl_seconds: int,
        request_timeout_seconds: float,
    ) -> TelegramSettings:
        if not 60 <= int(link_ttl_seconds) <= 3600:
            raise ValueError("link_ttl_seconds must be within 60..3600")
        if not 1 <= float(request_timeout_seconds) <= 30:
            raise ValueError("request_timeout_seconds must be within 1..30")
        values = (
            bool(enabled),
            self._seal_for_write(bot_token),
            (bot_username or "").strip().lstrip("@"),
            self._seal_for_write(webhook_secret),
            int(link_ttl_seconds),
            float(request_timeout_seconds),
        )
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO telegram_settings
                        (id, enabled, bot_token_envelope, bot_username,
                         webhook_secret_envelope, link_ttl_seconds,
                         request_timeout_seconds, updated_at)
                    VALUES (1, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET
                        enabled = EXCLUDED.enabled,
                        bot_token_envelope = EXCLUDED.bot_token_envelope,
                        bot_username = EXCLUDED.bot_username,
                        webhook_secret_envelope = EXCLUDED.webhook_secret_envelope,
                        link_ttl_seconds = EXCLUDED.link_ttl_seconds,
                        request_timeout_seconds = EXCLUDED.request_timeout_seconds,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING {_COLUMNS}
                    """,
                    values,
                )
                row = cursor.fetchone()
        if row is None:
            raise RuntimeError("Telegram settings upsert did not return a row")
        return self._row_to_settings(row)

    def delete_telegram_settings(self) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM telegram_settings WHERE id = 1")
                return int(cursor.rowcount)

    def _seal_for_write(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            return ""
        if self._secret_box is None:
            raise TelegramSettingsSecretError(
                "Telegram 配置加密密钥未配置（TELEGRAM_CONFIG_ENCRYPTION_KEY 或 PUSH_CHANNEL_ENCRYPTION_KEY），无法保存 bot token/webhook secret"
            )
        return json.dumps(self._secret_box.seal(value), ensure_ascii=False)

    def _unseal_for_read(self, value: Any) -> str:
        envelope = _parse_envelope(value)
        if envelope is None:
            if value:
                logger.warning("Telegram 配置发现非加密 secret，按未配置处理")
            return ""
        if self._secret_box is None:
            logger.warning("Telegram 配置加密密钥未配置，无法解密 secret")
            return ""
        try:
            return self._secret_box.unseal(envelope)
        except WeChatSecretBoxError as exc:
            logger.warning("Telegram 配置 secret 解密失败: %s", exc)
            return ""

    def _row_to_settings(self, row: dict[str, Any]) -> TelegramSettings:
        return TelegramSettings(
            enabled=bool(row.get("enabled")),
            bot_token=self._unseal_for_read(row.get("bot_token_envelope")),
            bot_username=str(row.get("bot_username") or ""),
            webhook_secret=self._unseal_for_read(row.get("webhook_secret_envelope")),
            link_ttl_seconds=int(row.get("link_ttl_seconds") or 300),
            request_timeout_seconds=float(row.get("request_timeout_seconds") or 5.0),
            updated_at=row.get("updated_at") if isinstance(row.get("updated_at"), datetime) else None,
        )
