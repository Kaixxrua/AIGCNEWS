from __future__ import annotations

from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.payment_settings_repository import PaymentSettings

_COLUMNS = (
    "enabled, order_ttl_minutes, public_base_url, wechat_appid, wechat_mchid, "
    "wechat_mch_serial_no, wechat_api_v3_key, wechat_private_key_pem, alipay_appid, "
    "alipay_private_key_pem, alipay_public_key_pem, stripe_secret_key, stripe_webhook_secret, updated_at"
)


class PostgresPaymentSettingsRepository:
    """PostgreSQL persistence for the singleton payment settings row (id = 1)."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def get_payment_settings(self) -> PaymentSettings | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT {_COLUMNS} FROM payment_settings WHERE id = 1")
                row = cursor.fetchone()
                return self._row_to_settings(row) if row else None

    def upsert_payment_settings(
        self,
        *,
        enabled: bool,
        order_ttl_minutes: int,
        public_base_url: str,
        wechat_appid: str,
        wechat_mchid: str,
        wechat_mch_serial_no: str,
        wechat_api_v3_key: str,
        wechat_private_key_pem: str,
        alipay_appid: str,
        alipay_private_key_pem: str,
        alipay_public_key_pem: str,
        stripe_secret_key: str,
        stripe_webhook_secret: str,
    ) -> PaymentSettings:
        ttl = int(order_ttl_minutes)
        if not 5 <= ttl <= 1440:
            raise ValueError("order_ttl_minutes 必须在 5-1440 之间")
        values = (
            bool(enabled), ttl, (public_base_url or "").strip(),
            wechat_appid or "", wechat_mchid or "", wechat_mch_serial_no or "",
            wechat_api_v3_key or "", wechat_private_key_pem or "", alipay_appid or "",
            alipay_private_key_pem or "", alipay_public_key_pem or "", stripe_secret_key or "",
            stripe_webhook_secret or "",
        )
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO payment_settings
                        (id, enabled, order_ttl_minutes, public_base_url, wechat_appid,
                         wechat_mchid, wechat_mch_serial_no, wechat_api_v3_key,
                         wechat_private_key_pem, alipay_appid, alipay_private_key_pem,
                         alipay_public_key_pem, stripe_secret_key, stripe_webhook_secret,
                         updated_at)
                    VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET
                        enabled = EXCLUDED.enabled, order_ttl_minutes = EXCLUDED.order_ttl_minutes,
                        public_base_url = EXCLUDED.public_base_url, wechat_appid = EXCLUDED.wechat_appid,
                        wechat_mchid = EXCLUDED.wechat_mchid, wechat_mch_serial_no = EXCLUDED.wechat_mch_serial_no,
                        wechat_api_v3_key = EXCLUDED.wechat_api_v3_key, wechat_private_key_pem = EXCLUDED.wechat_private_key_pem,
                        alipay_appid = EXCLUDED.alipay_appid, alipay_private_key_pem = EXCLUDED.alipay_private_key_pem,
                        alipay_public_key_pem = EXCLUDED.alipay_public_key_pem, stripe_secret_key = EXCLUDED.stripe_secret_key,
                        stripe_webhook_secret = EXCLUDED.stripe_webhook_secret, updated_at = CURRENT_TIMESTAMP
                    RETURNING {_COLUMNS}
                    """,
                    values,
                )
                row = cursor.fetchone()
        return self._row_to_settings(row)

    def delete_payment_settings(self) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM payment_settings WHERE id = 1")
                return int(cursor.rowcount)

    @staticmethod
    def _row_to_settings(row: dict[str, Any]) -> PaymentSettings:
        return PaymentSettings(
            enabled=bool(row["enabled"]), order_ttl_minutes=int(row["order_ttl_minutes"]),
            public_base_url=str(row["public_base_url"]), wechat_appid=str(row["wechat_appid"]),
            wechat_mchid=str(row["wechat_mchid"]), wechat_mch_serial_no=str(row["wechat_mch_serial_no"]),
            wechat_api_v3_key=str(row["wechat_api_v3_key"]), wechat_private_key_pem=str(row["wechat_private_key_pem"]),
            alipay_appid=str(row["alipay_appid"]), alipay_private_key_pem=str(row["alipay_private_key_pem"]),
            alipay_public_key_pem=str(row["alipay_public_key_pem"]), stripe_secret_key=str(row["stripe_secret_key"]),
            stripe_webhook_secret=str(row["stripe_webhook_secret"]), updated_at=row["updated_at"],
        )
