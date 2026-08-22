"""Runtime payment configuration: DB singleton override with a short TTL cache."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Literal

from backend.app.core.config import settings
from backend.app.repositories.payment_settings_repository import PaymentSettings, PaymentSettingsReader

logger = logging.getLogger(__name__)
PaymentConfigSource = Literal["database", "environment", "unconfigured"]
_CACHE_TTL_SECONDS = 60.0


@dataclass(frozen=True)
class EffectivePaymentConfig:
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
    stripe_secret_key: str
    stripe_webhook_secret: str
    source: PaymentConfigSource


_reader: PaymentSettingsReader | None = None
_cache: tuple[float, EffectivePaymentConfig] | None = None
_lock = threading.Lock()


def configure_payment_settings_reader(reader: PaymentSettingsReader | None) -> None:
    global _reader, _cache
    with _lock:
        _reader, _cache = reader, None


def invalidate_payment_config_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def reset_payment_config_provider() -> None:
    configure_payment_settings_reader(None)


def _environment_config(env: object) -> EffectivePaymentConfig:
    values = dict(
        enabled=bool(getattr(env, "payments_enabled", False)),
        order_ttl_minutes=int(getattr(env, "payments_order_ttl_minutes", 30)),
        public_base_url=str(getattr(env, "payments_public_base_url", "") or ""),
        wechat_appid=str(getattr(env, "wechat_pay_appid", "") or ""),
        wechat_mchid=str(getattr(env, "wechat_pay_mchid", "") or ""),
        wechat_mch_serial_no=str(getattr(env, "wechat_pay_mch_serial_no", "") or ""),
        wechat_api_v3_key=str(getattr(env, "wechat_pay_api_v3_key", "") or ""),
        wechat_private_key_pem=str(getattr(env, "wechat_pay_private_key_path", "") or ""),
        wechat_public_key_id=str(getattr(env, "wechat_pay_public_key_id", "") or ""),
        wechat_public_key_pem=str(getattr(env, "wechat_pay_public_key_path", "") or ""),
        alipay_appid=str(getattr(env, "alipay_appid", "") or ""),
        alipay_private_key_pem=str(getattr(env, "alipay_private_key_path", "") or ""),
        alipay_public_key_pem=str(getattr(env, "alipay_public_key_path", "") or ""),
        stripe_secret_key=str(getattr(env, "stripe_secret_key", "") or ""),
        stripe_webhook_secret=str(getattr(env, "stripe_webhook_secret", "") or ""),
    )
    configured = any(values[key] for key in (
        "wechat_appid", "wechat_mchid", "wechat_api_v3_key", "alipay_appid",
        "stripe_secret_key", "stripe_webhook_secret",
    ))
    return EffectivePaymentConfig(**values, source="environment" if configured or values["enabled"] else "unconfigured")


def effective_payment_config_from_row(row: PaymentSettings, *, env: object = settings) -> EffectivePaymentConfig:
    fallback = _environment_config(env)
    return EffectivePaymentConfig(
        enabled=row.enabled,
        order_ttl_minutes=row.order_ttl_minutes,
        public_base_url=row.public_base_url,
        wechat_appid=row.wechat_appid,
        wechat_mchid=row.wechat_mchid,
        wechat_mch_serial_no=row.wechat_mch_serial_no,
        wechat_api_v3_key=row.wechat_api_v3_key or fallback.wechat_api_v3_key,
        wechat_private_key_pem=row.wechat_private_key_pem or fallback.wechat_private_key_pem,
        wechat_public_key_id=row.wechat_public_key_id,
        wechat_public_key_pem=row.wechat_public_key_pem or fallback.wechat_public_key_pem,
        alipay_appid=row.alipay_appid,
        alipay_private_key_pem=row.alipay_private_key_pem or fallback.alipay_private_key_pem,
        alipay_public_key_pem=row.alipay_public_key_pem or fallback.alipay_public_key_pem,
        stripe_secret_key=row.stripe_secret_key or fallback.stripe_secret_key,
        stripe_webhook_secret=row.stripe_webhook_secret or fallback.stripe_webhook_secret,
        source="database",
    )


def resolve_payment_config(*, env=settings) -> EffectivePaymentConfig:
    global _cache
    with _lock:
        if _cache is not None and time.monotonic() - _cache[0] < _CACHE_TTL_SECONDS:
            return _cache[1]
        fallback = _environment_config(env)
        row = None
        if _reader is not None:
            try:
                row = _reader.get_payment_settings()
            except Exception:
                logger.warning("[Payments] 读取 payment_settings 失败，回退 env 配置", exc_info=True)
        config = effective_payment_config_from_row(row, env=env) if row is not None else fallback
        if _reader is not None:
            _cache = (time.monotonic(), config)
        return config
