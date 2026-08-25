from __future__ import annotations

"""payment_order_closing 周期关单 job 的调度器接线测试，镜像
test_scheduler_x_media_warmup.py 的既有模式。
"""

import asyncio
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from backend.app.core import scheduler
from backend.app.core.config import settings
from backend.app.core.scheduler_registry import PAYMENT_ORDER_CLOSING_JOB
from backend.app.repositories.payment_settings_repository import PaymentSettings
from backend.app.services.payments.config_admin import PaymentConfigAdminService
from backend.app.services.payments.runtime_config import (
    configure_payment_settings_reader,
    reset_payment_config_provider,
)


def _runtime(**overrides) -> scheduler.ApplicationSchedulerRuntime:
    fake_scheduler = MagicMock()
    fake_scheduler.running = False
    fake_scheduler.get_jobs.return_value = []
    kwargs = {
        "scheduler": fake_scheduler,
        "payments_enabled": True,
    }
    kwargs.update(overrides)
    runtime = scheduler.ApplicationSchedulerRuntime(MagicMock(), **kwargs)
    return runtime, fake_scheduler


def _start(runtime: scheduler.ApplicationSchedulerRuntime) -> None:
    with patch.object(scheduler.asyncio, "get_running_loop") as get_loop:
        def close_coroutine(coroutine):
            coroutine.close()
            return MagicMock()

        get_loop.return_value.create_task.side_effect = close_coroutine
        runtime.start()


class PaymentOrderClosingJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_job_expires_overdue_orders_via_writer(self) -> None:
        orders = MagicMock()
        orders.mark_expired_overdue.return_value = 3

        result = await scheduler._run_payment_order_closing_job(orders)

        self.assertTrue(result)
        orders.mark_expired_overdue.assert_called_once()
        kwargs = orders.mark_expired_overdue.call_args.kwargs
        self.assertEqual(kwargs["limit"], scheduler._PAYMENT_ORDER_CLOSING_BATCH_LIMIT)
        now = kwargs["now"]
        self.assertIsInstance(now, datetime)
        self.assertIs(now.tzinfo, timezone.utc)

    async def test_job_returns_false_on_repository_failure(self) -> None:
        orders = MagicMock()
        orders.mark_expired_overdue.side_effect = RuntimeError("炸了")

        result = await scheduler._run_payment_order_closing_job(orders)

        self.assertFalse(result)


class PaymentOrderClosingRegistrationTests(unittest.TestCase):
    def test_registers_five_minute_interval_job_when_enabled(self) -> None:
        runtime, fake_scheduler = _runtime()
        _start(runtime)

        call = next(
            item
            for item in fake_scheduler.add_job.call_args_list
            if item.kwargs.get("id") == "payment_order_closing"
        )
        self.assertEqual(call.kwargs["trigger"].interval.total_seconds(), 300)
        self.assertEqual(str(call.kwargs["trigger"].timezone), "Asia/Shanghai")
        self.assertEqual(call.kwargs["max_instances"], 1)
        self.assertTrue(call.kwargs["coalesce"])

    def test_not_registered_when_payments_disabled(self) -> None:
        runtime, fake_scheduler = _runtime(payments_enabled=False)
        _start(runtime)

        self.assertFalse(
            any(
                item.kwargs.get("id") == "payment_order_closing"
                for item in fake_scheduler.add_job.call_args_list
            )
        )

    def test_resolve_callback_none_when_disabled_for_live_apply(self) -> None:
        # 在线配置尝试启用时，开关关闭必须拿不到 callback 与 base descriptor
        runtime, _ = _runtime(payments_enabled=False)

        self.assertIsNone(runtime._resolve_callback(PAYMENT_ORDER_CLOSING_JOB))
        self.assertIsNone(runtime._base_descriptor("payment_order_closing"))

    def test_runtime_callback_forwards_orders_repository(self) -> None:
        from unittest.mock import AsyncMock

        repositories = MagicMock()
        runtime = scheduler.ApplicationSchedulerRuntime(
            repositories,
            payments_enabled=True,
        )
        closing = AsyncMock(return_value=True)

        with patch.object(
            scheduler,
            "_run_payment_order_closing_job",
            new=closing,
        ):
            import asyncio

            asyncio.run(runtime._run_payment_order_closing_job())

        closing.assert_awaited_once_with(repositories.orders)



def _payment_settings_row(*, enabled: bool) -> PaymentSettings:
    return PaymentSettings(
        enabled=enabled,
        order_ttl_minutes=30,
        public_base_url="",
        wechat_appid="",
        wechat_mchid="",
        wechat_mch_serial_no="",
        wechat_api_v3_key="",
        wechat_private_key_pem="",
        wechat_public_key_id="",
        wechat_public_key_pem="",
        alipay_appid="",
        alipay_private_key_pem="",
        alipay_public_key_pem="",
        overseas_provider="",
        overseas_sandbox=False,
        overseas_client_id="",
        overseas_client_secret="",
        overseas_webhook_secret="",
        updated_at=datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc),
    )


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


class PaymentOrderClosingHotToggleTests(unittest.TestCase):
    """reader 已绑定（生产形态）时，关单任务热启停以 DB 覆盖行为准，无需重建调度器。"""

    def setUp(self) -> None:
        reset_payment_config_provider()

    def tearDown(self) -> None:
        reset_payment_config_provider()

    @staticmethod
    def _bind(*, enabled: bool) -> FakePaymentSettingsRepository:
        repo = FakePaymentSettingsRepository(_payment_settings_row(enabled=enabled))
        configure_payment_settings_reader(repo)
        return repo

    def test_db_row_overrides_constructor_param_when_reader_bound(self) -> None:
        # 冷启动 env/构造参数关闭，但面板已在 DB 打开 → 注册关单任务
        self._bind(enabled=True)
        runtime, fake_scheduler = _runtime(payments_enabled=False)
        _start(runtime)

        self.assertTrue(
            any(
                item.kwargs.get("id") == "payment_order_closing"
                for item in fake_scheduler.add_job.call_args_list
            )
        )

    def test_panel_save_toggles_descriptor_and_callback_without_rebuild(self) -> None:
        repo = self._bind(enabled=True)
        service = PaymentConfigAdminService(repo, env_config=settings)
        runtime, _ = _runtime(payments_enabled=True)

        self.assertIsNotNone(runtime._base_descriptor("payment_order_closing"))
        self.assertIsNotNone(runtime._resolve_callback(PAYMENT_ORDER_CLOSING_JOB))

        # 面板关闭 → 同一 runtime 立即不再暴露 descriptor/callback
        asyncio.run(service.update_config({"enabled": False, "order_ttl_minutes": 30}))
        self.assertIsNone(runtime._base_descriptor("payment_order_closing"))
        self.assertIsNone(runtime._resolve_callback(PAYMENT_ORDER_CLOSING_JOB))

        # 面板重新打开 → 恢复
        asyncio.run(service.update_config({"enabled": True, "order_ttl_minutes": 30}))
        self.assertIsNotNone(runtime._base_descriptor("payment_order_closing"))
        self.assertIsNotNone(runtime._resolve_callback(PAYMENT_ORDER_CLOSING_JOB))

    def test_row_delete_falls_back_to_environment_settings(self) -> None:
        repo = self._bind(enabled=True)
        service = PaymentConfigAdminService(repo, env_config=settings)
        runtime, _ = _runtime(payments_enabled=False)

        self.assertIsNotNone(runtime._base_descriptor("payment_order_closing"))

        # 删除覆盖行 → 回落 env（此处钉死为关）→ 立即下线
        with patch.object(settings, "payments_enabled", False):
            asyncio.run(service.reset_config())
            self.assertIsNone(runtime._base_descriptor("payment_order_closing"))


if __name__ == "__main__":
    unittest.main()
