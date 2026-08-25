from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class PaymentSettings:
    """Singleton payment configuration stored at the same protection level as env."""

    enabled: bool
    order_ttl_minutes: int
    public_base_url: str
    wechat_appid: str
    wechat_mchid: str
    wechat_mch_serial_no: str
    wechat_api_v3_key: str
    wechat_private_key_pem: str
    wechat_public_key_id: str
    wechat_public_key_pem: str
    alipay_appid: str
    alipay_private_key_pem: str
    alipay_public_key_pem: str
    overseas_provider: str
    overseas_sandbox: bool
    overseas_client_id: str
    overseas_client_secret: str
    overseas_webhook_secret: str
    updated_at: datetime | None = None


class PaymentSettingsReader(Protocol):
    def get_payment_settings(self) -> PaymentSettings | None: ...


class PaymentSettingsManager(PaymentSettingsReader, Protocol):
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
        wechat_public_key_id: str,
        wechat_public_key_pem: str,
        alipay_appid: str,
        alipay_private_key_pem: str,
        alipay_public_key_pem: str,
        overseas_provider: str,
        overseas_sandbox: bool,
        overseas_client_id: str,
        overseas_client_secret: str,
        overseas_webhook_secret: str,
    ) -> PaymentSettings: ...

    def delete_payment_settings(self) -> int: ...


class PaymentSettingsRepository(PaymentSettingsManager, Protocol):
    """Persistence boundary for the singleton payment settings row."""
