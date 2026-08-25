from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

from backend.app.core.config import settings
from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.domain.wechat_secret_box import WeChatSecretBox, WeChatSecretBoxError
from backend.app.repositories.oauth_settings_repository import OAuthSettings

logger = logging.getLogger(__name__)

_SECRET_FIELDS = (
    ("github_client_secret", "github_client_secret_envelope"),
    ("google_client_secret", "google_client_secret_envelope"),
    ("wechat_app_secret", "wechat_app_secret_envelope"),
)
_COLUMNS = (
    "enabled_providers, public_base_url, github_client_id, "
    "github_client_secret_envelope, google_client_id, google_client_secret_envelope, "
    "wechat_app_id, wechat_app_secret_envelope, state_ttl_seconds, "
    "handoff_ttl_seconds, updated_at"
)
_SECRET_BOX_UNSET: Any = object()


class OAuthSettingsSecretError(ValueError):
    """OAuth secrets must never be written without the deployment key."""


def build_oauth_settings_secret_box(*, config=settings) -> WeChatSecretBox | None:
    key = str(getattr(config, "oauth_config_encryption_key", "") or "")
    if not key:
        return None
    try:
        return WeChatSecretBox.from_urlsafe_base64(
            key,
            str(getattr(config, "oauth_config_encryption_key_version", "v1")),
        )
    except WeChatSecretBoxError as exc:
        logger.warning("OAuth 配置加密密钥非法: %s", exc)
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


class PostgresOAuthSettingsRepository:
    """Singleton OAuth configuration with AES-GCM sealed secrets."""

    def __init__(
        self,
        database: PostgresDatabaseLifecycle,
        *,
        secret_box: WeChatSecretBox | None = _SECRET_BOX_UNSET,
    ) -> None:
        self._database = database
        self._secret_box = (
            build_oauth_settings_secret_box()
            if secret_box is _SECRET_BOX_UNSET
            else secret_box
        )

    def get_oauth_settings(self) -> OAuthSettings | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT {_COLUMNS} FROM oauth_settings WHERE id = 1")
                row = cursor.fetchone()
        return self._row_to_settings(row) if row else None

    def upsert_oauth_settings(
        self,
        *,
        enabled_providers: str,
        public_base_url: str,
        github_client_id: str,
        github_client_secret: str,
        google_client_id: str,
        google_client_secret: str,
        wechat_app_id: str,
        wechat_app_secret: str,
        state_ttl_seconds: int,
        handoff_ttl_seconds: int,
    ) -> OAuthSettings:
        if not 60 <= int(state_ttl_seconds) <= 900:
            raise ValueError("state_ttl_seconds must be within 60..900")
        if not 30 <= int(handoff_ttl_seconds) <= 600:
            raise ValueError("handoff_ttl_seconds must be within 30..600")
        values = (
            (enabled_providers or "").strip(),
            (public_base_url or "").strip().rstrip("/"),
            (github_client_id or "").strip(),
            self._seal_for_write(github_client_secret),
            (google_client_id or "").strip(),
            self._seal_for_write(google_client_secret),
            (wechat_app_id or "").strip(),
            self._seal_for_write(wechat_app_secret),
            int(state_ttl_seconds),
            int(handoff_ttl_seconds),
        )
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO oauth_settings
                        (id, enabled_providers, public_base_url, github_client_id,
                         github_client_secret_envelope, google_client_id,
                         google_client_secret_envelope, wechat_app_id,
                         wechat_app_secret_envelope, state_ttl_seconds,
                         handoff_ttl_seconds, updated_at)
                    VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET
                        enabled_providers = EXCLUDED.enabled_providers,
                        public_base_url = EXCLUDED.public_base_url,
                        github_client_id = EXCLUDED.github_client_id,
                        github_client_secret_envelope = EXCLUDED.github_client_secret_envelope,
                        google_client_id = EXCLUDED.google_client_id,
                        google_client_secret_envelope = EXCLUDED.google_client_secret_envelope,
                        wechat_app_id = EXCLUDED.wechat_app_id,
                        wechat_app_secret_envelope = EXCLUDED.wechat_app_secret_envelope,
                        state_ttl_seconds = EXCLUDED.state_ttl_seconds,
                        handoff_ttl_seconds = EXCLUDED.handoff_ttl_seconds,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING {_COLUMNS}
                    """,
                    values,
                )
                row = cursor.fetchone()
        if row is None:
            raise RuntimeError("OAuth settings upsert did not return a row")
        return self._row_to_settings(row)

    def delete_oauth_settings(self) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM oauth_settings WHERE id = 1")
                return int(cursor.rowcount)

    def _seal_for_write(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            return ""
        if self._secret_box is None:
            raise OAuthSettingsSecretError(
                "OAuth 配置加密密钥未配置，无法保存 client secret/app secret"
            )
        return json.dumps(self._secret_box.seal(value), ensure_ascii=False)

    def _unseal_for_read(self, value: Any) -> str:
        envelope = _parse_envelope(value)
        if envelope is None:
            if value:
                logger.warning("OAuth 配置发现非加密 secret，按未配置处理")
            return ""
        if self._secret_box is None:
            logger.warning("OAuth 配置加密密钥未配置，无法解密 secret")
            return ""
        try:
            return self._secret_box.unseal(envelope)
        except WeChatSecretBoxError as exc:
            logger.warning("OAuth 配置 secret 解密失败: %s", exc)
            return ""

    def _row_to_settings(self, row: dict[str, Any]) -> OAuthSettings:
        return OAuthSettings(
            enabled_providers=str(row.get("enabled_providers") or ""),
            public_base_url=str(row.get("public_base_url") or ""),
            github_client_id=str(row.get("github_client_id") or ""),
            github_client_secret=self._unseal_for_read(row.get("github_client_secret_envelope")),
            google_client_id=str(row.get("google_client_id") or ""),
            google_client_secret=self._unseal_for_read(row.get("google_client_secret_envelope")),
            wechat_app_id=str(row.get("wechat_app_id") or ""),
            wechat_app_secret=self._unseal_for_read(row.get("wechat_app_secret_envelope")),
            state_ttl_seconds=int(row.get("state_ttl_seconds") or 300),
            handoff_ttl_seconds=int(row.get("handoff_ttl_seconds") or 120),
            updated_at=row.get("updated_at") if isinstance(row.get("updated_at"), datetime) else None,
        )
