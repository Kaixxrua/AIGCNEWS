"""PaymentConfigAdminService 的投影脱敏与 keep/clear/env 回落语义契约测试。

钉住的对外语义：
- 投影绝不回明文：密文只有 *_configured 布尔 + *_masked 脱敏值；
- 更新密文留空 = 保留 DB 现值；显式 clear_* = 擦除（擦除后回落 env）；
- DB 行整体覆盖 env 的开关/TTL/基址，密文列逐字段空值回落 env（SMTP 先例）；
- 保存即失效运行时缓存；reader 故障静默回退 env（非致命）。
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.repositories.payment_settings_repository import PaymentSettings
from backend.app.services.payments.config_admin import PaymentConfigAdminService
from backend.app.services.payments.runtime_config import (
    configure_payment_settings_reader,
    invalidate_payment_config_cache,
    reset_payment_config_provider,
    resolve_payment_config,
)

ENV_SECRET = "env-overseas-secret-0001"
DB_SECRET = "db-overseas-secret-0002"


def _env(**overrides):
    values = {
        "payments_enabled": False,
        "payments_order_ttl_minutes": 45,
        "payments_public_base_url": "https://env-pay.example.test",
        "wechat_pay_appid": "",
        "wechat_pay_mchid": "",
        "wechat_pay_mch_serial_no": "",
        "wechat_pay_api_v3_key": "",
        "wechat_pay_private_key_path": "",
        "wechat_pay_public_key_id": "",
        "wechat_pay_public_key_path": "",
        "alipay_appid": "",
        "alipay_private_key_path": "",
        "alipay_public_key_path": "",
        "overseas_payment_provider": "",
        "overseas_payment_sandbox": False,
        "overseas_payment_client_id": "",
        "overseas_payment_client_secret": ENV_SECRET,
        "overseas_payment_webhook_secret": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _row(**overrides) -> PaymentSettings:
    values = {
        "enabled": True,
        "order_ttl_minutes": 60,
        "public_base_url": "https://db-pay.example.test",
        "wechat_appid": "wx-db",
        "wechat_mchid": "1600000000",
        "wechat_mch_serial_no": "SERIAL-DB",
        "wechat_api_v3_key": "db-api-v3-key-0123456789",
        "wechat_private_key_pem": "-----BEGIN PRIVATE KEY-----\ndb\n-----END PRIVATE KEY-----",
        "wechat_public_key_id": "PUB_KEY_ID_DB",
        "wechat_public_key_pem": "-----BEGIN PUBLIC KEY-----\ndb\n-----END PUBLIC KEY-----",
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
        self.upsert_calls: list[dict] = []
        self.delete_calls = 0

    def get_payment_settings(self) -> PaymentSettings | None:
        return self._row

    def upsert_payment_settings(self, **kwargs) -> PaymentSettings:
        self.upsert_calls.append(kwargs)
        self._row = PaymentSettings(
            **kwargs,
            updated_at=datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc),
        )
        return self._row

    def delete_payment_settings(self) -> int:
        self.delete_calls += 1
        had_row = self._row is not None
        self._row = None
        return 1 if had_row else 0


class PaymentConfigAdminTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        reset_payment_config_provider()

    async def test_projection_masks_secrets_and_never_exposes_plaintext(self) -> None:
        repo = FakePaymentSettingsRepository(_row(overseas_client_secret=DB_SECRET))
        configure_payment_settings_reader(repo)
        service = PaymentConfigAdminService(repo, env_config=_env())

        projection = await service.get_config()

        self.assertEqual(projection.source, "database")
        self.assertTrue(projection.enabled)
        self.assertEqual(projection.order_ttl_minutes, 60)
        self.assertTrue(projection.wechat_configured)
        self.assertFalse(projection.alipay_configured)
        self.assertTrue(projection.overseas_client_secret_configured)
        self.assertEqual(projection.overseas_client_secret_masked, "db-o****0002")
        fields = projection.__dict__
        self.assertNotIn(DB_SECRET, str(fields))
        self.assertNotIn(ENV_SECRET, str(fields))
        self.assertNotIn("db-api-v3-key-0123456789", str(fields))
        # 投影 schema 里不存在任何明文密钥键
        self.assertFalse(any(key.endswith("_key") or key.endswith("_pem") for key in fields))

    async def test_blank_db_secret_falls_back_to_env_per_field(self) -> None:
        # DB 行存在但 overseas_client_secret 留空 → 回落 env；开关/TTL 仍按 DB 口径
        repo = FakePaymentSettingsRepository(_row())
        configure_payment_settings_reader(repo)
        service = PaymentConfigAdminService(repo, env_config=_env())

        projection = await service.get_config()

        self.assertEqual(projection.source, "database")
        self.assertTrue(projection.overseas_client_secret_configured)
        self.assertEqual(projection.overseas_client_secret_masked, "env-****0001")
        self.assertFalse(projection.overseas_webhook_secret_configured)

    async def test_unconfigured_without_row_or_env(self) -> None:
        repo = FakePaymentSettingsRepository()
        configure_payment_settings_reader(repo)
        service = PaymentConfigAdminService(repo, env_config=_env(overseas_payment_client_secret=""))

        projection = await service.get_config()

        self.assertEqual(projection.source, "unconfigured")
        self.assertFalse(projection.enabled)
        self.assertIsNone(projection.updated_at)
        self.assertFalse(projection.wechat_configured)

    async def test_update_retains_existing_secret_when_submitted_blank(self) -> None:
        repo = FakePaymentSettingsRepository(_row(overseas_client_secret=DB_SECRET))
        service = PaymentConfigAdminService(repo, env_config=_env())

        await service.update_config({"enabled": True, "order_ttl_minutes": 30})

        saved = repo.upsert_calls[-1]
        self.assertEqual(saved["overseas_client_secret"], DB_SECRET)

    async def test_update_clear_flag_wipes_secret_down_to_env_fallback(self) -> None:
        repo = FakePaymentSettingsRepository(_row(overseas_client_secret=DB_SECRET))
        service = PaymentConfigAdminService(repo, env_config=_env())

        projection = await service.update_config(
            {"enabled": True, "order_ttl_minutes": 30, "clear_overseas_client_secret": True}
        )

        saved = repo.upsert_calls[-1]
        self.assertEqual(saved["overseas_client_secret"], "")
        # 擦除 DB 值后回落 env，投影按生效值给 configured/masked
        self.assertTrue(projection.overseas_client_secret_configured)
        self.assertEqual(projection.overseas_client_secret_masked, "env-****0001")

    async def test_update_stores_new_secret_and_masks_it(self) -> None:
        repo = FakePaymentSettingsRepository()
        service = PaymentConfigAdminService(repo, env_config=_env())

        projection = await service.update_config(
            {"enabled": True, "order_ttl_minutes": 30, "overseas_client_secret": "pp-live-newsecret1234"}
        )

        saved = repo.upsert_calls[-1]
        self.assertEqual(saved["overseas_client_secret"], "pp-live-newsecret1234")
        self.assertEqual(projection.overseas_client_secret_masked, "pp-l****1234")
        self.assertNotIn("pp-live-newsecret1234", str(projection.__dict__))

    async def test_overseas_configured_requires_provider_and_three_credentials(self) -> None:
        # 四项齐全才算已配置：provider + client_id + client_secret + webhook_secret
        repo = FakePaymentSettingsRepository(
            _row(
                overseas_provider="paypal",
                overseas_client_id="client-id",
                overseas_client_secret="client-secret",
                overseas_webhook_secret="webhook-id",
            )
        )
        configure_payment_settings_reader(repo)
        service = PaymentConfigAdminService(repo, env_config=_env(overseas_payment_client_secret=""))
        self.assertTrue((await service.get_config()).overseas_configured)

        for missing in ("overseas_provider", "overseas_client_id", "overseas_client_secret", "overseas_webhook_secret"):
            partial = dict(
                overseas_provider="paypal",
                overseas_client_id="client-id",
                overseas_client_secret="client-secret",
                overseas_webhook_secret="webhook-id",
            )
            partial[missing] = ""
            repo = FakePaymentSettingsRepository(_row(**partial))
            configure_payment_settings_reader(repo)
            service = PaymentConfigAdminService(repo, env_config=_env(overseas_payment_client_secret=""))
            self.assertFalse((await service.get_config()).overseas_configured, missing)

    async def test_update_rejects_unknown_overseas_provider(self) -> None:
        repo = FakePaymentSettingsRepository()
        service = PaymentConfigAdminService(repo, env_config=_env())

        for provider in ("paypal", "pingpong", ""):
            await service.update_config({"enabled": True, "order_ttl_minutes": 30, "overseas_provider": provider})
        self.assertEqual(len(repo.upsert_calls), 3)

        with self.assertRaises(ValueError):
            await service.update_config({"enabled": True, "order_ttl_minutes": 30, "overseas_provider": "stripe"})
        self.assertEqual(len(repo.upsert_calls), 3)

    async def test_update_validates_ttl_and_base_url(self) -> None:
        repo = FakePaymentSettingsRepository()
        service = PaymentConfigAdminService(repo, env_config=_env())

        with self.assertRaises(ValueError):
            await service.update_config({"order_ttl_minutes": 4})
        with self.assertRaises(ValueError):
            await service.update_config({"order_ttl_minutes": 1441})
        with self.assertRaises(ValueError):
            await service.update_config({"public_base_url": "not-a-url"})
        with self.assertRaises(ValueError):
            await service.update_config({"public_base_url": "ftp://pay.example.test"})
        self.assertEqual(repo.upsert_calls, [])

    async def test_update_rejects_changeme_placeholders(self) -> None:
        repo = FakePaymentSettingsRepository()
        service = PaymentConfigAdminService(repo, env_config=_env())

        with self.assertRaises(ValueError):
            await service.update_config({"wechat_appid": "CHANGEME-wechat-appid"})
        with self.assertRaises(ValueError):
            await service.update_config({"overseas_client_secret": "CHANGEME-overseas"})
        self.assertEqual(repo.upsert_calls, [])

    async def test_update_normalizes_base_url_trailing_slash(self) -> None:
        repo = FakePaymentSettingsRepository()
        service = PaymentConfigAdminService(repo, env_config=_env())

        await service.update_config({"public_base_url": "https://pay.example.test/"})

        self.assertEqual(repo.upsert_calls[-1]["public_base_url"], "https://pay.example.test")

    async def test_update_invalidates_runtime_cache(self) -> None:
        repo = FakePaymentSettingsRepository(_row(enabled=False))
        configure_payment_settings_reader(repo)
        self.assertFalse(resolve_payment_config(env=_env()).enabled)

        service = PaymentConfigAdminService(repo, env_config=_env())
        await service.update_config({"enabled": True, "order_ttl_minutes": 30})

        # 保存即失效：下一次 resolve 立刻读到新行，不等 60s TTL
        self.assertTrue(resolve_payment_config(env=_env()).enabled)

    async def test_reset_deletes_row_and_falls_back_to_env(self) -> None:
        repo = FakePaymentSettingsRepository(_row())
        configure_payment_settings_reader(repo)
        service = PaymentConfigAdminService(repo, env_config=_env())

        projection = await service.reset_config()

        self.assertEqual(repo.delete_calls, 1)
        self.assertEqual(projection.source, "environment")
        self.assertFalse(projection.enabled)
        self.assertEqual(projection.order_ttl_minutes, 45)


class RuntimeConfigResolutionTests(unittest.TestCase):
    """resolve_payment_config：DB 覆盖 env、reader 故障回退、缓存只在绑定时生效。"""

    def tearDown(self) -> None:
        reset_payment_config_provider()

    def test_db_row_overrides_env_wholesale_for_non_secret_fields(self) -> None:
        repo = FakePaymentSettingsRepository(_row())
        configure_payment_settings_reader(repo)

        config = resolve_payment_config(env=_env())

        self.assertEqual(config.source, "database")
        self.assertTrue(config.enabled)
        self.assertEqual(config.order_ttl_minutes, 60)
        self.assertEqual(config.public_base_url, "https://db-pay.example.test")
        # DB 空密文逐字段回落 env
        self.assertEqual(config.overseas_client_secret, ENV_SECRET)

    def test_no_row_falls_back_to_environment(self) -> None:
        configure_payment_settings_reader(FakePaymentSettingsRepository())

        config = resolve_payment_config(env=_env())

        self.assertEqual(config.source, "environment")
        self.assertEqual(config.order_ttl_minutes, 45)
        self.assertEqual(config.overseas_client_secret, ENV_SECRET)

    def test_reader_failure_falls_back_to_env_non_fatal(self) -> None:
        class BrokenReader:
            def get_payment_settings(self) -> PaymentSettings | None:
                raise RuntimeError("db down")

        configure_payment_settings_reader(BrokenReader())

        config = resolve_payment_config(env=_env())

        self.assertEqual(config.source, "environment")
        self.assertEqual(config.overseas_client_secret, ENV_SECRET)

    def test_cache_holds_within_ttl_and_invalidate_forces_reload(self) -> None:
        repo = FakePaymentSettingsRepository(_row(enabled=False))
        configure_payment_settings_reader(repo)
        self.assertFalse(resolve_payment_config(env=_env()).enabled)

        # 缓存窗口内直接改行不可见
        repo._row = _row(enabled=True)
        self.assertFalse(resolve_payment_config(env=_env()).enabled)

        invalidate_payment_config_cache()
        self.assertTrue(resolve_payment_config(env=_env()).enabled)


if __name__ == "__main__":
    unittest.main()
