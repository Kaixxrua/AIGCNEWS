from __future__ import annotations

import json
import logging
from typing import Any

from backend.app.core.config import settings
from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.domain.wechat_secret_box import (
    WeChatSecretBox,
    WeChatSecretBoxError,
)

logger = logging.getLogger(__name__)


class XCredentialSecretError(Exception):
    """X 凭证加解密失败或加密密钥配置不可用。"""


# 构造期 secret_box 缺省哨兵：未显式传入时按 settings 装配（与推送渠道
# build_push_channel_secret_box 同口径），显式 None 表示"无加密盒"（测试缝）。
_SECRET_BOX_UNSET: Any = object()

_ENVELOPE_KEYS = ("v", "ct", "nonce")


def _parse_sealed_envelope(value: Any) -> dict[str, str] | None:
    """识别密封信封字符串（box.seal 的 JSON 序列化）；非信封返回 None。

    历史明文 cookie 是纯 token 串，永远不会解析成带 v/ct/nonce 的 JSON
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


def build_x_credential_secret_box(*, config=settings) -> WeChatSecretBox | None:
    """构建 X 凭证加密盒；未配置或密钥非法时返回 None（不阻塞启动）。

    返回 None 时使用处自行拒绝处理 secret（写侧不降级为明文；历史明文行
    仍可读），对齐微信/推送渠道密钥的装配策略。
    """
    key = config.x_credential_encryption_key
    if not key:
        return None
    try:
        return WeChatSecretBox.from_urlsafe_base64(
            key,
            config.x_credential_encryption_key_version,
        )
    except WeChatSecretBoxError as exc:
        logger.warning("X 凭证加密密钥非法: %s", exc)
        return None


class PostgresXCredentialRepository:
    """PostgreSQL persistence for the X cookie credential pool.

    auth_token/ct0 以 AES-256-GCM 密封信封落库（复用 WeChatSecretBox）：
    写入侧一律密封；读取侧识别信封并解密还原明文，历史明文行原样兼容
    （懒迁移：下次写入即密封）。读取方（采集 transport、探测、后台投影）
    因此始终拿到明文，无需感知加密。密钥未配置时拒绝写入 secret，绝不
    降级为明文。
    """

    def __init__(
        self,
        database: PostgresDatabaseLifecycle,
        bootstrap: tuple[str, str] | None = None,
        secret_box: WeChatSecretBox | None = _SECRET_BOX_UNSET,
    ) -> None:
        self._database = database
        self._bootstrap = bootstrap
        self._secret_box = (
            build_x_credential_secret_box()
            if secret_box is _SECRET_BOX_UNSET
            else secret_box
        )

    @staticmethod
    def _clean_secret(value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    def _seal_for_write(self, plaintext: str) -> str:
        """密封待写入的 secret；密钥未配置时拒绝（不写明文）。"""
        if self._secret_box is None:
            raise XCredentialSecretError(
                "X 凭证加密密钥未配置，无法存储凭证 secret"
            )
        envelope = self._secret_box.seal(plaintext)
        return json.dumps(envelope, ensure_ascii=False)

    def _carry_or_seal(self, stored: Any) -> str:
        """保留既有存储值：已密封的原样携带；历史明文立即密封迁移。"""
        if _parse_sealed_envelope(stored) is not None:
            return str(stored)
        return self._seal_for_write(self._clean_secret(stored))

    def _unseal_for_read(self, stored: Any) -> str:
        """读取侧还原明文：信封解密，历史明文原样返回。

        密钥缺失或解密失败（密钥轮换/数据损坏）时记告警并返回空串，该
        凭证对下游表现为"未配置"，绝不把密文当明文泄露给采集链路。
        """
        value = self._clean_secret(stored)
        if not value:
            return ""
        envelope = _parse_sealed_envelope(value)
        if envelope is None:
            return value
        if self._secret_box is None:
            logger.warning("[XCredentials] 加密密钥未配置，无法解密封存的凭证")
            return ""
        try:
            return self._secret_box.unseal(envelope)
        except WeChatSecretBoxError as exc:
            logger.warning("[XCredentials] 凭证解密失败: %s", exc)
            return ""

    def _project_row(self, row: dict[str, Any]) -> dict[str, Any]:
        projected = dict(row)
        projected["auth_token"] = self._unseal_for_read(row.get("auth_token"))
        projected["ct0"] = self._unseal_for_read(row.get("ct0"))
        return projected

    def ensure_seeded_from_env(self) -> None:
        if not self._bootstrap:
            return
        auth_token, ct0 = (self._clean_secret(value) for value in self._bootstrap)
        if not auth_token or not ct0:
            return
        if self._secret_box is None:
            # 种子也是 secret 写入：无密钥时跳过而非落明文（下次列表仍会尝试）
            logger.warning(
                "[XCredentials] 加密密钥未配置，跳过 env 凭证种子写入"
            )
            return
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext('x_credentials_bootstrap'))"
                )
                cursor.execute(
                    "SELECT 1 FROM x_credentials_bootstrap_state WHERE singleton_key = 1"
                )
                if cursor.fetchone() is not None:
                    return
                cursor.execute("SELECT COUNT(*) AS n FROM x_credentials")
                row = cursor.fetchone()
                count = int(
                    (row["n"] if isinstance(row, dict) else row[0]) if row else 0
                )
                if count:
                    cursor.execute(
                        """
                        INSERT INTO x_credentials_bootstrap_state (singleton_key)
                        VALUES (1)
                        ON CONFLICT (singleton_key) DO NOTHING
                        """
                    )
                    return
                cursor.execute(
                    """
                    INSERT INTO x_credentials
                        (display_name, note, auth_token, ct0, enabled, sort_order)
                    VALUES (%s, %s, %s, %s, TRUE, 0)
                    """,
                    (
                        "env-bootstrap",
                        "由环境变量初始化；请在 Monitor 的 X 凭证池中管理。",
                        self._seal_for_write(auth_token),
                        self._seal_for_write(ct0),
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO x_credentials_bootstrap_state (singleton_key)
                    VALUES (1)
                    ON CONFLICT (singleton_key) DO NOTHING
                    """
                )

    @staticmethod
    def _select_sql() -> str:
        return """
            SELECT id, display_name, note, auth_token, ct0, enabled, sort_order,
                   last_test_status, last_test_message, last_test_at,
                   created_at, updated_at
            FROM x_credentials
        """

    def list_x_credentials(self) -> list[dict[str, Any]]:
        self.ensure_seeded_from_env()
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(self._select_sql() + " ORDER BY enabled DESC, sort_order ASC, id ASC")
                return [self._project_row(row) for row in cursor.fetchall()]

    def get_x_credential(self, credential_id: int) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(self._select_sql() + " WHERE id = %s LIMIT 1", (credential_id,))
                row = cursor.fetchone()
                return self._project_row(row) if row else None

    def _get_stored_row(self, credential_id: int) -> dict[str, Any] | None:
        """读取未解密的原始行（更新路径保留既有信封时使用）。"""
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(self._select_sql() + " WHERE id = %s LIMIT 1", (credential_id,))
                row = cursor.fetchone()
                return dict(row) if row else None

    def list_enabled_x_credentials(self) -> list[dict[str, Any]]:
        self.ensure_seeded_from_env()
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    self._select_sql()
                    + " WHERE enabled ORDER BY sort_order ASC, id ASC"
                )
                return [self._project_row(row) for row in cursor.fetchall()]

    def create_x_credential(self, payload: dict[str, Any]) -> dict[str, Any]:
        auth_token = self._clean_secret(payload.get("auth_token"))
        ct0 = self._clean_secret(payload.get("ct0"))
        if not auth_token or not ct0:
            raise ValueError("auth_token 和 ct0 不能为空")
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO x_credentials
                        (display_name, note, auth_token, ct0, enabled, sort_order)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        str(payload.get("display_name") or "").strip(),
                        str(payload.get("note") or "").strip(),
                        self._seal_for_write(auth_token),
                        self._seal_for_write(ct0),
                        bool(payload.get("enabled", True)),
                        int(payload.get("sort_order", 0)),
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("PostgreSQL X credential insert did not return an id")
                credential_id = int(row["id"])
        return self.get_x_credential(credential_id) or {}

    def update_x_credential(
        self,
        credential_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        existing = self._get_stored_row(credential_id)
        if not existing:
            return None
        # 新 secret 密封写入；留空则保留既有存储值（信封原样携带，历史
        # 明文立即密封迁移——任何写路径都不再产出明文行）。
        new_auth_token = self._clean_secret(payload.get("auth_token"))
        new_ct0 = self._clean_secret(payload.get("ct0"))
        if not new_auth_token and not self._clean_secret(existing.get("auth_token")):
            raise ValueError("auth_token 和 ct0 不能为空")
        if not new_ct0 and not self._clean_secret(existing.get("ct0")):
            raise ValueError("auth_token 和 ct0 不能为空")
        auth_token = (
            self._seal_for_write(new_auth_token)
            if new_auth_token
            else self._carry_or_seal(existing.get("auth_token"))
        )
        ct0 = (
            self._seal_for_write(new_ct0)
            if new_ct0
            else self._carry_or_seal(existing.get("ct0"))
        )
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE x_credentials
                    SET display_name = %s,
                        note = %s,
                        auth_token = %s,
                        ct0 = %s,
                        enabled = %s,
                        sort_order = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (
                        str(payload.get("display_name") or existing.get("display_name") or "").strip(),
                        str(payload.get("note") if "note" in payload else existing.get("note") or "").strip(),
                        auth_token,
                        ct0,
                        bool(payload.get("enabled", bool(existing.get("enabled")))),
                        int(payload.get("sort_order", int(existing.get("sort_order") or 0))),
                        credential_id,
                    ),
                )
        return self.get_x_credential(credential_id)

    def delete_x_credential(self, credential_id: int) -> bool:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM x_credentials WHERE id = %s", (credential_id,))
                return cursor.rowcount > 0

    def update_x_credential_test_result(
        self,
        credential_id: int,
        result: dict[str, Any],
    ) -> dict[str, Any] | None:
        status = str(result.get("status") or "unknown").strip().lower()
        message = str(result.get("message") or "").strip()
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE x_credentials
                    SET last_test_status = %s,
                        last_test_message = %s,
                        last_test_at = CURRENT_TIMESTAMP,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (status, message, credential_id),
                )
                if cursor.rowcount <= 0:
                    return None
        return self.get_x_credential(credential_id)
