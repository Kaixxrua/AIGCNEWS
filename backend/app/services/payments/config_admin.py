"""Safe admin projection and update semantics for runtime payment configuration."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from backend.app.core.config import settings
from backend.app.repositories.payment_settings_repository import PaymentSettingsManager
from backend.app.services.payments.runtime_config import (
    EffectivePaymentConfig,
    invalidate_payment_config_cache,
    resolve_payment_config,
)
from backend.app.services.secret_masking import mask_token

_SECRET_FIELDS = (
    "wechat_api_v3_key",
    "wechat_private_key_pem",
    "wechat_public_key_pem",
    "alipay_private_key_pem",
    "alipay_public_key_pem",
    "stripe_secret_key",
    "stripe_webhook_secret",
)
_TEXT_FIELDS = (
    "wechat_appid", "wechat_mchid", "wechat_mch_serial_no", "wechat_public_key_id", "alipay_appid",
)


@dataclass(frozen=True)
class PaymentConfigProjection:
    enabled: bool
    order_ttl_minutes: int
    public_base_url: str
    wechat_appid: str
    wechat_mchid: str
    wechat_mch_serial_no: str
    wechat_public_key_id: str
    alipay_appid: str
    source: str
    updated_at: str | None
    wechat_configured: bool
    alipay_configured: bool
    stripe_configured: bool
    wechat_api_v3_key_configured: bool
    wechat_api_v3_key_masked: str | None
    wechat_private_key_pem_configured: bool
    wechat_private_key_pem_masked: str | None
    wechat_public_key_pem_configured: bool
    wechat_public_key_pem_masked: str | None
    alipay_private_key_pem_configured: bool
    alipay_private_key_pem_masked: str | None
    alipay_public_key_pem_configured: bool
    alipay_public_key_pem_masked: str | None
    stripe_secret_key_configured: bool
    stripe_secret_key_masked: str | None
    stripe_webhook_secret_configured: bool
    stripe_webhook_secret_masked: str | None


class PaymentConfigAdminService:
    def __init__(self, repository: PaymentSettingsManager, *, env_config=settings) -> None:
        self._repository = repository
        self._env = env_config

    async def get_config(self) -> PaymentConfigProjection:
        effective = resolve_payment_config(env=self._env)
        row = await asyncio.to_thread(self._repository.get_payment_settings)
        return self._to_projection(effective, row.updated_at.isoformat() if row and row.updated_at else None)

    async def update_config(self, values: Mapping[str, Any]) -> PaymentConfigProjection:
        ttl = int(values.get("order_ttl_minutes") or 30)
        if not 5 <= ttl <= 1440:
            raise ValueError("订单过期分钟数必须在 5-1440 之间")
        base_url = str(values.get("public_base_url") or "").strip().rstrip("/")
        if base_url:
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("公网回调基址必须是 http(s) 绝对地址")
        text = {field: str(values.get(field) or "").strip() for field in _TEXT_FIELDS}
        if any(value.startswith("CHANGEME") for value in text.values()):
            raise ValueError("支付配置不得使用 CHANGEME 示例占位符")
        existing = await asyncio.to_thread(self._repository.get_payment_settings)
        secret_values: dict[str, str] = {}
        for field in _SECRET_FIELDS:
            submitted = values.get(field)
            if bool(values.get(f"clear_{field}", False)):
                secret_values[field] = ""
            elif submitted:
                value = str(submitted)
                if value.startswith("CHANGEME"):
                    raise ValueError("支付密钥不得使用 CHANGEME 示例占位符")
                secret_values[field] = value
            else:
                secret_values[field] = getattr(existing, field, "") if existing else ""
        saved = await asyncio.to_thread(
            self._repository.upsert_payment_settings,
            enabled=bool(values.get("enabled", False)), order_ttl_minutes=ttl,
            public_base_url=base_url, **text, **secret_values,
        )
        invalidate_payment_config_cache()
        from backend.app.services.payments.runtime_config import effective_payment_config_from_row

        return self._to_projection(
            effective_payment_config_from_row(saved, env=self._env),
            saved.updated_at.isoformat() if saved.updated_at else None,
        )

    async def reset_config(self) -> PaymentConfigProjection:
        await asyncio.to_thread(self._repository.delete_payment_settings)
        invalidate_payment_config_cache()
        return await self.get_config()

    @staticmethod
    def _to_projection(config: EffectivePaymentConfig, updated_at: str | None) -> PaymentConfigProjection:
        return PaymentConfigProjection(
            enabled=config.enabled, order_ttl_minutes=config.order_ttl_minutes,
            public_base_url=config.public_base_url, wechat_appid=config.wechat_appid,
            wechat_mchid=config.wechat_mchid, wechat_mch_serial_no=config.wechat_mch_serial_no,
            wechat_public_key_id=config.wechat_public_key_id,
            alipay_appid=config.alipay_appid, source=config.source, updated_at=updated_at,
            wechat_configured=all((config.wechat_appid, config.wechat_mchid, config.wechat_mch_serial_no,
                                    config.wechat_api_v3_key, config.wechat_private_key_pem,
                                    config.wechat_public_key_id, config.wechat_public_key_pem)),
            alipay_configured=all((config.alipay_appid, config.alipay_private_key_pem, config.alipay_public_key_pem)),
            stripe_configured=all((config.stripe_secret_key, config.stripe_webhook_secret)),
            **{f"{field}_configured": bool(getattr(config, field)) for field in _SECRET_FIELDS},
            **{f"{field}_masked": mask_token(getattr(config, field)) for field in _SECRET_FIELDS},
        )
