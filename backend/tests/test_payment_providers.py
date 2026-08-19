"""渠道桩与配置契约单测（支付骨架 PR-2）。

骨架期渠道能力刻意未实现：create/verify/query 一律 ProviderNotConfiguredError
（路由映射 503），但 ACK 应答报文形状必须现在就钉住——形状错了渠道会
无限重发，这是与微信/支付宝/Stripe 的线上契约。
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings
from backend.app.services.payments.providers.alipay_page import (
    CHANNEL_ALIPAY_PAGE,
    AlipayPagePaymentProvider,
)
from backend.app.services.payments.providers.base import ProviderNotConfiguredError
from backend.app.services.payments.providers.registry import build_payment_providers
from backend.app.services.payments.providers.stripe import (
    CHANNEL_STRIPE,
    StripePaymentProvider,
)
from backend.app.services.payments.providers.wechat_native import (
    CHANNEL_WECHAT_NATIVE,
    WeChatNativePaymentProvider,
)


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


# ── 注册表与 is_configured ─────────────────────────────────────────────


def test_registry_builds_all_three_channels() -> None:
    providers = build_payment_providers(_settings())
    assert set(providers) == {
        CHANNEL_WECHAT_NATIVE,
        CHANNEL_ALIPAY_PAGE,
        CHANNEL_STRIPE,
    }
    assert providers[CHANNEL_WECHAT_NATIVE].channel == CHANNEL_WECHAT_NATIVE


def test_unconfigured_by_default() -> None:
    providers = build_payment_providers(_settings())
    assert all(not provider.is_configured() for provider in providers.values())


def test_wechat_configured_requires_full_credential_set() -> None:
    full = dict(
        wechat_pay_appid="wx123",
        wechat_pay_mchid="1900000109",
        wechat_pay_mch_serial_no="SERIAL",
        wechat_pay_api_v3_key="k" * 32,
        wechat_pay_private_key_path="/secrets/apiclient_key.pem",
    )
    assert WeChatNativePaymentProvider(_settings(**full)).is_configured() is True
    # 缺任意一项即不可用（fail-closed）
    for missing in full:
        partial = {**full, missing: ""}
        assert WeChatNativePaymentProvider(_settings(**partial)).is_configured() is False


def test_alipay_and_stripe_configured_checks() -> None:
    alipay_full = dict(
        alipay_appid="2021000000000000",
        alipay_private_key_path="/secrets/app_private.pem",
        alipay_public_key_path="/secrets/alipay_public.pem",
    )
    assert AlipayPagePaymentProvider(_settings(**alipay_full)).is_configured() is True
    assert AlipayPagePaymentProvider(_settings(alipay_appid="only")).is_configured() is False

    stripe_full = dict(stripe_secret_key="sk_live_x", stripe_webhook_secret="whsec_x")
    assert StripePaymentProvider(_settings(**stripe_full)).is_configured() is True
    assert StripePaymentProvider(_settings(stripe_secret_key="sk_live_x")).is_configured() is False


# ── 骨架期能力：一律未配置 ─────────────────────────────────────────────


def test_stub_capabilities_raise_provider_not_configured() -> None:
    provider = WeChatNativePaymentProvider(_settings())
    order = {"order_no": "P1"}
    with pytest.raises(ProviderNotConfiguredError):
        provider.create_payment(order=order, notify_url="https://x/cb", return_url=None)
    with pytest.raises(ProviderNotConfiguredError):
        provider.verify_and_parse_callback(raw_body=b"{}", headers={})
    with pytest.raises(ProviderNotConfiguredError):
        provider.query_order(order=order)

    alipay = AlipayPagePaymentProvider(_settings())
    with pytest.raises(ProviderNotConfiguredError):
        alipay.create_payment(order=order, notify_url="https://x/cb", return_url=None)

    stripe = StripePaymentProvider(_settings())
    with pytest.raises(ProviderNotConfiguredError):
        stripe.verify_and_parse_callback(raw_body=b"{}", headers={})


# ── ACK 应答契约（与渠道的线上约定，骨架期即钉死） ──────────────────────


def test_wechat_ack_contract() -> None:
    provider = WeChatNativePaymentProvider(_settings())
    ok = provider.build_ack_response(ok=True)
    assert ok.status_code == 200
    assert json.loads(bytes(ok.body)) == {"code": "SUCCESS", "message": "成功"}
    fail = provider.build_ack_response(ok=False)
    assert fail.status_code == 400
    assert json.loads(bytes(fail.body))["code"] == "FAIL"


def test_alipay_ack_contract_is_plain_text() -> None:
    provider = AlipayPagePaymentProvider(_settings())
    ok = provider.build_ack_response(ok=True)
    assert ok.status_code == 200
    assert bytes(ok.body) == b"success"
    assert ok.media_type == "text/plain"
    fail = provider.build_ack_response(ok=False)
    assert fail.status_code == 400
    assert bytes(fail.body) == b"failure"


def test_stripe_ack_contract_is_empty_json() -> None:
    provider = StripePaymentProvider(_settings())
    ok = provider.build_ack_response(ok=True)
    assert ok.status_code == 200
    assert json.loads(bytes(ok.body)) == {}
    assert provider.build_ack_response(ok=False).status_code == 400


# ── 配置契约 ────────────────────────────────────────────────────────────


def test_payments_settings_defaults_keep_feature_dark() -> None:
    settings = _settings()
    assert settings.payments_enabled is False
    assert settings.payments_order_ttl_minutes == 30
    assert settings.payments_public_base_url == ""
    assert settings.wechat_pay_appid == ""
    assert settings.stripe_secret_key == ""


def test_payments_order_ttl_bounds() -> None:
    assert _settings(payments_order_ttl_minutes=5).payments_order_ttl_minutes == 5
    assert _settings(payments_order_ttl_minutes=1440).payments_order_ttl_minutes == 1440
    for bad in (0, 4, 1441):
        with pytest.raises(ValidationError):
            _settings(payments_order_ttl_minutes=bad)


def test_payment_secrets_reject_changeme_placeholder() -> None:
    for field, value in (
        ("wechat_pay_api_v3_key", "CHANGEME-api-v3-key"),
        ("stripe_secret_key", "CHANGEME"),
        ("stripe_webhook_secret", "CHANGEME-whsec"),
    ):
        with pytest.raises(ValidationError):
            _settings(**{field: value})
