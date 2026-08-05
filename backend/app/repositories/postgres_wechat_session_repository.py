from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.domain.wechat_secret_box import (
    WeChatSecretBox,
    WeChatSecretBoxError,
)
from backend.app.repositories.wechat_session_repository import (
    WeChatLoginAttemptRepository,
    WeChatSessionRepository,
)

logger = logging.getLogger(__name__)


class PostgresWeChatSessionRepository(
    WeChatLoginAttemptRepository,
    WeChatSessionRepository,
):
    """PostgreSQL persistence for encrypted WeChat login attempts and sessions."""

    def __init__(
        self,
        database: PostgresDatabaseLifecycle,
        secret_box: WeChatSecretBox | None,
    ) -> None:
        self._database = database
        self._secret_box = secret_box

    def _require_box(self) -> WeChatSecretBox:
        if self._secret_box is None:
            raise WeChatSecretBoxError(
                "WeChat session encryption is not configured"
            )
        return self._secret_box

    def _encrypt(self, plaintext: str) -> tuple[str, str]:
        envelope = self._require_box().seal(plaintext)
        return envelope["ct"], envelope["nonce"]

    def _decrypt(self, ciphertext: str, nonce: str) -> str | None:
        try:
            return self._require_box().decrypt(ciphertext, nonce)
        except WeChatSecretBoxError as exc:
            logger.warning("Failed to decrypt WeChat secret: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Login attempts
    # ------------------------------------------------------------------

    def create_login_attempt(
        self,
        owner_id: int,
        attempt_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        uuid_cookie = str(payload.get("uuid_cookie") or "")
        if not uuid_cookie:
            raise ValueError("uuid_cookie is required")
        encrypted_cookie, nonce = self._encrypt(uuid_cookie)
        expires_at = payload["expires_at"]
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO wechat_login_attempts (
                        attempt_id, owner_id, encrypted_uuid_cookie,
                        encrypted_uuid_cookie_nonce, encryption_key_version,
                        status, expires_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        str(attempt_id),
                        owner_id,
                        encrypted_cookie,
                        nonce,
                        self._secret_box.key_version,
                        "waiting_scan",
                        expires_at,
                    ),
                )
        return self.get_login_attempt(owner_id, attempt_id) or {}

    def get_login_attempt(
        self,
        owner_id: int,
        attempt_id: UUID,
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT attempt_id, owner_id, encrypted_uuid_cookie,
                           encrypted_uuid_cookie_nonce, encryption_key_version,
                           status, upstream_status, expires_at, error_code,
                           created_at, updated_at
                    FROM wechat_login_attempts
                    WHERE attempt_id = %s AND owner_id = %s
                    LIMIT 1
                    """,
                    (str(attempt_id), owner_id),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                data = dict(row)
        decrypted = self._decrypt(
            data.pop("encrypted_uuid_cookie"),
            data.pop("encrypted_uuid_cookie_nonce"),
        )
        if decrypted is None:
            return None
        data["uuid_cookie"] = decrypted
        return data

    def update_login_attempt(
        self,
        owner_id: int,
        attempt_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE wechat_login_attempts
                    SET status = COALESCE(%s, status),
                        upstream_status = COALESCE(%s, upstream_status),
                        error_code = COALESCE(%s, error_code),
                        expires_at = COALESCE(%s, expires_at),
                        updated_at = CURRENT_TIMESTAMP
                    WHERE attempt_id = %s AND owner_id = %s
                    """,
                    (
                        payload.get("status"),
                        payload.get("upstream_status"),
                        payload.get("error_code"),
                        payload.get("expires_at"),
                        str(attempt_id),
                        owner_id,
                    ),
                )
                if cursor.rowcount <= 0:
                    return None
        return self.get_login_attempt(owner_id, attempt_id)

    def delete_login_attempt(self, owner_id: int, attempt_id: UUID) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM wechat_login_attempts WHERE attempt_id = %s AND owner_id = %s",
                    (str(attempt_id), owner_id),
                )
                return cursor.rowcount > 0

    def expire_login_attempts(self, owner_id: int) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DELETE FROM wechat_login_attempts
                    WHERE owner_id = %s AND expires_at < CURRENT_TIMESTAMP
                    """,
                    (owner_id,),
                )
                return cursor.rowcount

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def _session_select_sql(self) -> str:
        return """
            SELECT id, owner_id, encrypted_token, encrypted_token_nonce,
                   encrypted_cookie, encrypted_cookie_nonce, encryption_key_version,
                   status, account_name, account_avatar_url,
                   last_validated_at, last_used_at, expires_at, invalid_reason_code,
                   created_at, updated_at
            FROM wechat_sessions
            WHERE owner_id = %s
            LIMIT 1
        """

    def _decrypt_session_row(self, row: dict[str, Any]) -> dict[str, Any] | None:
        data = dict(row)
        token = self._decrypt(
            data.pop("encrypted_token"),
            data.pop("encrypted_token_nonce"),
        )
        cookie = self._decrypt(
            data.pop("encrypted_cookie"),
            data.pop("encrypted_cookie_nonce"),
        )
        if token is None or cookie is None:
            return None
        data["token"] = token
        data["cookie"] = cookie
        return data

    def get_wechat_session(self, owner_id: int) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(self._session_select_sql(), (owner_id,))
                row = cursor.fetchone()
                if row is None:
                    return None
        return self._decrypt_session_row(row)

    def save_wechat_session(
        self,
        owner_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        token = str(payload.get("token") or "")
        cookie = str(payload.get("cookie") or "")
        if not token or not cookie:
            raise ValueError("token and cookie are required")
        encrypted_token, token_nonce = self._encrypt(token)
        encrypted_cookie, cookie_nonce = self._encrypt(cookie)
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO wechat_sessions (
                        owner_id, encrypted_token, encrypted_token_nonce,
                        encrypted_cookie, encrypted_cookie_nonce,
                        encryption_key_version, status, account_name,
                        account_avatar_url, last_validated_at, last_used_at,
                        expires_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (owner_id) DO UPDATE SET
                        encrypted_token = EXCLUDED.encrypted_token,
                        encrypted_token_nonce = EXCLUDED.encrypted_token_nonce,
                        encrypted_cookie = EXCLUDED.encrypted_cookie,
                        encrypted_cookie_nonce = EXCLUDED.encrypted_cookie_nonce,
                        encryption_key_version = EXCLUDED.encryption_key_version,
                        status = EXCLUDED.status,
                        account_name = EXCLUDED.account_name,
                        account_avatar_url = EXCLUDED.account_avatar_url,
                        last_validated_at = EXCLUDED.last_validated_at,
                        last_used_at = EXCLUDED.last_used_at,
                        expires_at = EXCLUDED.expires_at,
                        invalid_reason_code = NULL,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        owner_id,
                        encrypted_token,
                        token_nonce,
                        encrypted_cookie,
                        cookie_nonce,
                        self._secret_box.key_version,
                        payload.get("status", "active"),
                        str(payload.get("account_name") or ""),
                        str(payload.get("account_avatar_url") or ""),
                        payload.get("last_validated_at"),
                        payload.get("last_used_at"),
                        payload.get("expires_at"),
                    ),
                )
        return self.get_wechat_session(owner_id) or {}

    def mark_wechat_session_invalid(
        self,
        owner_id: int,
        reason_code: str,
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE wechat_sessions
                    SET status = 'invalid',
                        invalid_reason_code = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE owner_id = %s
                    """,
                    (reason_code, owner_id),
                )
                if cursor.rowcount <= 0:
                    return None
        return self.get_wechat_session(owner_id)

    def delete_wechat_session(self, owner_id: int) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM wechat_sessions WHERE owner_id = %s",
                    (owner_id,),
                )
                return cursor.rowcount > 0
