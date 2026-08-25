"""渠道注册表、配置契约与 ACK 应答形状单测。

三渠道（微信 Native / 支付宝 page.pay / 海外跳转 overseas_redirect）均已真实接入；
本文件钉住的是跨渠道契约：注册表完整性、海外单槽按 overseas_provider 分发
（paypal/pingpong，未选或未知值落 fail-closed 桩，绝不 KeyError）、
is_configured fail-closed 语义（缺任意一项凭证即 503）、ACK 应答报文形状
（形状错了渠道会无限重发）。PayPal/PingPong 各自的报文/验签钉在专属测试文件。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings
from backend.app.services.payments.providers.alipay_page import (
    CHANNEL_ALIPAY_PAGE,
    AlipayPagePaymentProvider,
)
from backend.app.services.payments.providers.base import ProviderNotConfiguredError
from backend.app.services.payments.providers.overseas_redirect import (
    CHANNEL_OVERSEAS_REDIRECT,
    UnselectedOverseasProvider,
)
from backend.app.services.payments.providers.paypal import PayPalProvider
from backend.app.services.payments.providers.pingpong import PingPongProvider
from backend.app.services.payments.providers.registry import build_payment_providers
from backend.app.services.payments.providers.wechat_native import (
    CHANNEL_WECHAT_NATIVE,
    WeChatNativePaymentProvider,
)


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def _overseas_config(**overrides: object) -> SimpleNamespace:
    """EffectivePaymentConfig 形态的海外槽配置（registry 的权威输入）。"""
    values = {
        "overseas_provider": "",
        "overseas_sandbox": True,
        "overseas_client_id": "",
        "overseas_client_secret": "",
        "overseas_webhook_secret": "",
        "public_base_url": "https://pay.example.test",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# ── 注册表与分发 ─────────────────────────────────────────────────────────


def test_registry_builds_all_three_channels() -> None:
    providers = build_payment_providers(_settings())
    assert set(providers) == {
        CHANNEL_WECHAT_NATIVE,
        CHANNEL_ALIPAY_PAGE,
        CHANNEL_OVERSEAS_REDIRECT,
    }
    assert providers[CHANNEL_WECHAT_NATIVE].channel == CHANNEL_WECHAT_NATIVE


def test_overseas_slot_dispatches_by_provider_name() -> None:
    paypal = build_payment_providers(_overseas_config(overseas_provider="paypal"))
    assert isinstance(paypal[CHANNEL_OVERSEAS_REDIRECT], PayPalProvider)
    pingpong = build_payment_providers(_overseas_config(overseas_provider="PingPong"))
    assert isinstance(pingpong[CHANNEL_OVERSEAS_REDIRECT], PingPongProvider)
    # 未选/未知值一律落 fail-closed 桩，绝不 KeyError/半初始化
    for name in ("", "stripe", "unknown"):
        providers = build_payment_providers(_overseas_config(overseas_provider=name))
        provider = providers[CHANNEL_OVERSEAS_REDIRECT]
        assert isinstance(provider, UnselectedOverseasProvider), name
        assert provider.channel == CHANNEL_OVERSEAS_REDIRECT


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
        wechat_pay_public_key_id="PUB_KEY_ID_0114",
        wechat_pay_public_key_path="/secrets/wechat_pay_public_key.pem",
    )
    assert WeChatNativePaymentProvider(_settings(**full)).is_configured() is True
    # 缺任意一项即不可用（fail-closed）
    for missing in full:
        partial = {**full, missing: ""}
        assert WeChatNativePaymentProvider(_settings(**partial)).is_configured() is False


def test_alipay_configured_checks() -> None:
    alipay_full = dict(
        alipay_appid="2021000000000000",
        alipay_private_key_path="/secrets/app_private.pem",
        alipay_public_key_path="/secrets/alipay_public.pem",
    )
    assert AlipayPagePaymentProvider(_settings(**alipay_full)).is_configured() is True
    assert AlipayPagePaymentProvider(_settings(alipay_appid="only")).is_configured() is False


def test_overseas_configured_requires_full_credential_set() -> None:
    full = dict(
        overseas_provider="paypal",
        overseas_client_id="client-id",
        overseas_client_secret="client-secret",
        overseas_webhook_secret="webhook-id",
    )
    provider = build_payment_providers(_overseas_config(**full))[CHANNEL_OVERSEAS_REDIRECT]
    assert provider.is_configured() is True
    # 三凭证缺任意一项即不可用（fail-closed）
    for missing in ("overseas_client_id", "overseas_client_secret", "overseas_webhook_secret"):
        partial = {**full, missing: ""}
        provider = build_payment_providers(_overseas_config(**partial))[CHANNEL_OVERSEAS_REDIRECT]
        assert provider.is_configured() is False, missing


# ── 未配置即不可用：create/verify/query 一律 503 ──────────────────────


def test_unconfigured_capabilities_raise_provider_not_configured() -> None:
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


def test_unselected_overseas_stub_is_fail_closed() -> None:
    provider = UnselectedOverseasProvider(_overseas_config())
    order = {"order_no": "P1"}
    assert provider.is_configured() is False
    with pytest.raises(ProviderNotConfiguredError, match="not selected"):
        provider.create_payment(order=order, notify_url="https://x/cb", return_url=None)
    with pytest.raises(ProviderNotConfiguredError, match="not selected"):
        provider.verify_and_parse_callback(raw_body=b"{}", headers={})
    with pytest.raises(ProviderNotConfiguredError, match="not selected"):
        provider.query_order(order=order)


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


def test_unselected_overseas_ack_contract_is_empty_json() -> None:
    provider = UnselectedOverseasProvider()
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
    assert settings.overseas_payment_provider == ""
    assert settings.overseas_payment_sandbox is False
    assert settings.overseas_payment_client_id == ""
    assert settings.overseas_payment_client_secret == ""
    assert settings.overseas_payment_webhook_secret == ""


def test_payments_order_ttl_bounds() -> None:
    assert _settings(payments_order_ttl_minutes=5).payments_order_ttl_minutes == 5
    assert _settings(payments_order_ttl_minutes=1440).payments_order_ttl_minutes == 1440
    for bad in (0, 4, 1441):
        with pytest.raises(ValidationError):
            _settings(payments_order_ttl_minutes=bad)


def test_payment_secrets_reject_changeme_placeholder() -> None:
    for field, value in (
        ("wechat_pay_api_v3_key", "CHANGEME-api-v3-key"),
        ("overseas_payment_client_secret", "CHANGEME"),
        ("overseas_payment_webhook_secret", "CHANGEME-whsec"),
    ):
        with pytest.raises(ValidationError):
            _settings(**{field: value})
