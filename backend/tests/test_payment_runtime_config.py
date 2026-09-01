"""支付运行时配置热生效契约测试（面板 PR）。

钉住的对外语义：
- 面板保存 DB 覆盖行后，用户侧特性门控无需重启即翻转（404 ↔ 200）；
- provider is_configured 同时接受 env 形态（Settings，*_path）与
  面板形态（EffectivePaymentConfig，*_pem 内容）两种配置载体。
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import get_payment_providers
from backend.app.api.routes_payments import router
from backend.app.core.auth import RequireUser
from backend.app.core.config import settings
from backend.app.repositories.payment_settings_repository import PaymentSettings
from backend.app.services.payments.config_admin import PaymentConfigAdminService
from backend.app.services.payments.providers.registry import build_payment_providers
from backend.app.services.payments.runtime_config import (
    EffectivePaymentConfig,
    configure_payment_settings_reader,
    reset_payment_config_provider,
)


def _row(**overrides) -> PaymentSettings:
    values = {
        "enabled": False,
        "order_ttl_minutes": 30,
        "public_base_url": "",
        "wechat_appid": "",
        "wechat_mchid": "",
        "wechat_mch_serial_no": "",
        "wechat_api_v3_key": "",
        "wechat_private_key_pem": "",
        "wechat_public_key_id": "",
        "wechat_public_key_pem": "",
        "alipay_appid": "",
        "alipay_private_key_pem": "",
        "alipay_public_key_pem": "",
        "overseas_provider": "",
        "overseas_sandbox": False,
        "overseas_client_id": "",
        "overseas_client_secret": "",
        "overseas_webhook_secret": "",
        "updated_at": datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return PaymentSettings(**values)


class FakePaymentSettingsRepository:
    def __init__(self, row: PaymentSettings | None = None) -> None:
        self._row = row

    def get_payment_settings(self) -> PaymentSettings | None:
        return self._row

    def upsert_payment_settings(self, **kwargs) -> PaymentSettings:
        self._row = PaymentSettings(
            **kwargs,
            updated_at=datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc),
        )
        return self._row

    def delete_payment_settings(self) -> int:
        had_row = self._row is not None
        self._row = None
        return 1 if had_row else 0


def _effective(**overrides) -> EffectivePaymentConfig:
    values = {
        "enabled": True,
        "order_ttl_minutes": 30,
        "public_base_url": "",
        "wechat_appid": "",
        "wechat_mchid": "",
        "wechat_mch_serial_no": "",
        "wechat_api_v3_key": "",
        "wechat_private_key_pem": "",
        "wechat_public_key_id": "",
        "wechat_public_key_pem": "",
        "alipay_appid": "",
        "alipay_private_key_pem": "",
        "alipay_public_key_pem": "",
        "overseas_provider": "",
        "overseas_sandbox": False,
        "overseas_client_id": "",
        "overseas_client_secret": "",
        "overseas_webhook_secret": "",
        "source": "database",
    }
    values.update(overrides)
    return EffectivePaymentConfig(**values)


# ── 门控热翻转 ──────────────────────────────────────────────────────────


@pytest.fixture()
def harness(monkeypatch: pytest.MonkeyPatch):
    """绑定 DB reader 的用户侧 app；面板保存经真实服务失效缓存。"""
    # env 保持关闭：翻转必须来自 DB 覆盖行，不能是 env 泄漏
    monkeypatch.setattr(settings, "payments_enabled", False)
    repo = FakePaymentSettingsRepository(_row(enabled=False))
    configure_payment_settings_reader(repo)
    providers = build_payment_providers(_effective())

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[RequireUser] = lambda: {"user_id": 7, "role": "user"}
    app.dependency_overrides[get_payment_providers] = lambda: providers

    yield TestClient(app), repo

    reset_payment_config_provider()


def test_gate_hot_flips_on_panel_save_without_restart(harness) -> None:
    client, repo = harness
    assert client.get("/api/payments/plans").status_code == 404

    service = PaymentConfigAdminService(repo, env_config=settings)
    import asyncio

    asyncio.run(service.update_config({"enabled": True, "order_ttl_minutes": 30}))
    assert client.get("/api/payments/plans").status_code == 200

    asyncio.run(service.update_config({"enabled": False, "order_ttl_minutes": 30}))
    assert client.get("/api/payments/plans").status_code == 404

    # 删除覆盖行回落 env（本用例 env 为关）→ 立即回 404
    asyncio.run(service.update_config({"enabled": True, "order_ttl_minutes": 30}))
    assert client.get("/api/payments/plans").status_code == 200
    asyncio.run(service.reset_config())
    assert client.get("/api/payments/plans").status_code == 404


# ── provider is_configured 双形态 ────────────────────────────────────────


class ProviderDualFormTests(unittest.TestCase):
    def test_effective_config_with_pem_content_configures_wechat(self) -> None:
        providers = build_payment_providers(
            _effective(
                wechat_appid="wx123",
                wechat_mchid="1600000000",
                wechat_mch_serial_no="SERIAL",
                wechat_api_v3_key="k" * 32,
                wechat_private_key_pem="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----",
                wechat_public_key_id="PUB_KEY_ID_0114",
                wechat_public_key_pem="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----",
            )
        )
        assert providers["wechat_native"].is_configured() is True

    def test_effective_config_with_pem_content_configures_alipay_and_paypal(self) -> None:
        providers = build_payment_providers(
            _effective(
                alipay_appid="2021000000000000",
                alipay_private_key_pem="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----",
                alipay_public_key_pem="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----",
                overseas_provider="paypal",
                overseas_client_id="client-id",
                overseas_client_secret="client-secret",
                overseas_webhook_secret="webhook-id",
            )
        )
        assert providers["alipay_page"].is_configured() is True
        assert providers["overseas_redirect"].is_configured() is True

    def test_effective_config_missing_pieces_stays_unconfigured(self) -> None:
        providers = build_payment_providers(
            _effective(
                wechat_appid="wx123",
                overseas_provider="paypal",
                overseas_client_id="client-id",
            )
        )
        # 微信只有 appid 远不齐；paypal 缺 client_secret/webhook_id 不齐
        assert providers["wechat_native"].is_configured() is False
        assert providers["overseas_redirect"].is_configured() is False

    def test_env_settings_form_still_accepted(self) -> None:
        """env 形态（Settings，私钥按路径）回归：构造载体 duck-type 不破坏既有调用。"""
        from backend.app.core.config import Settings

        env = Settings(
            _env_file=None,
            wechat_pay_appid="wx123",
            wechat_pay_mchid="1600000000",
            wechat_pay_mch_serial_no="SERIAL",
            wechat_pay_api_v3_key="k" * 32,
            wechat_pay_private_key_path="/secrets/apiclient_key.pem",
            wechat_pay_public_key_id="PUB_KEY_ID_0114",
            wechat_pay_public_key_path="/secrets/wechat_pay_public_key.pem",
        )  # type: ignore[arg-type]
        providers = build_payment_providers(env)
        assert providers["wechat_native"].is_configured() is True


if __name__ == "__main__":
    unittest.main()
