"""SmtpConfigAdminService 的读写投影与测试投递语义契约测试。"""

from __future__ import annotations

import dataclasses
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.repositories.smtp_settings_repository import SmtpSettings
from backend.app.services.email.smtp_config_provider import (
    configure_smtp_settings_reader,
    reset_smtp_config_provider,
)
from backend.app.services.email.smtp_transport import SmtpDeliveryError
from backend.app.services.smtp_config_admin import (
    SmtpConfigAdminService,
    SmtpConfigProjection,
    SmtpNotConfiguredError,
    SmtpTestDeliveryError,
)


def _env(**overrides):
    values = {
        "SMTP_HOST": "env-smtp.example.test",
        "SMTP_PORT": 2525,
        "SMTP_USERNAME": "env-user",
        "SMTP_PASSWORD": "env-password",
        "SMTP_FROM_EMAIL": "env@example.test",
        "SMTP_FROM_NAME": "Env Sender",
        "SMTP_USE_TLS": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _row(**overrides) -> SmtpSettings:
    values = {
        "host": "db-smtp.example.test",
        "port": 465,
        "username": "db-user",
        "password": "db-secret",
        "from_email": "db@example.test",
        "from_name": "DB Sender",
        "use_tls": True,
        "updated_at": datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SmtpSettings(**values)


class FakeSmtpSettingsRepository:
    def __init__(self, row: SmtpSettings | None = None) -> None:
        self._row = row
        self.upsert_calls: list[dict] = []
        self.delete_calls = 0

    def get_smtp_settings(self) -> SmtpSettings | None:
        return self._row

    def upsert_smtp_settings(self, **kwargs) -> SmtpSettings:
        self.upsert_calls.append(kwargs)
        self._row = SmtpSettings(
            **kwargs,
            updated_at=datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc),
        )
        return self._row

    def delete_smtp_settings(self) -> int:
        self.delete_calls += 1
        had_row = self._row is not None
        self._row = None
        return 1 if had_row else 0


class FakeTransport:
    def __init__(self, error: SmtpDeliveryError | None = None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self._error = error

    async def send_plain(self, to_email: str, subject: str, body: str) -> None:
        self.calls.append((to_email, subject, body))
        if self._error is not None:
            raise self._error


class FakeTransportFactory:
    """记录收到的生效配置，返回预置 transport。"""

    def __init__(self, transport: FakeTransport) -> None:
        self._transport = transport
        self.configs = []

    def __call__(self, config):
        self.configs.append(config)
        return self._transport


def _valid_payload(**overrides) -> dict:
    payload = {
        "host": "db-smtp.example.test",
        "port": 465,
        "username": "db-user",
        "password": None,
        "clear_password": False,
        "from_email": "db@example.test",
        "from_name": "DB Sender",
        "use_tls": True,
    }
    payload.update(overrides)
    return payload


class SmtpConfigAdminServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.repo = FakeSmtpSettingsRepository()
        # 对齐生产 lifespan：admin 服务的投影经 provider 读 DB 行
        configure_smtp_settings_reader(self.repo)
        self.addCleanup(reset_smtp_config_provider)
        self.transport = FakeTransport()
        self.factory = FakeTransportFactory(self.transport)
        self.service = SmtpConfigAdminService(
            self.repo,
            env_config=_env(),
            transport_factory=self.factory,
        )

    async def test_get_config_reflects_database_row_without_plaintext(self) -> None:
        self.repo._row = _row()

        projection = await self.service.get_config()

        self.assertEqual(projection.source, "database")
        self.assertEqual(projection.host, "db-smtp.example.test")
        self.assertTrue(projection.password_configured)
        self.assertIsNotNone(projection.password_masked)
        self.assertNotIn("db-secret", projection.password_masked)
        self.assertEqual(
            projection.updated_at, "2026-08-12T10:00:00+00:00"
        )

    async def test_get_config_falls_back_to_env_when_row_missing(self) -> None:
        projection = await self.service.get_config()

        self.assertEqual(projection.source, "environment")
        self.assertEqual(projection.host, "env-smtp.example.test")
        self.assertIsNone(projection.updated_at)

    async def test_projection_never_carries_plaintext_password_field(self) -> None:
        field_names = {field.name for field in dataclasses.fields(SmtpConfigProjection)}

        self.assertNotIn("password", field_names)

    async def test_update_config_retains_stored_password_when_password_empty(
        self,
    ) -> None:
        self.repo._row = _row(password="keep-me")

        projection = await self.service.update_config(_valid_payload(password=None))

        self.assertEqual(self.repo.upsert_calls[0]["password"], "keep-me")
        self.assertEqual(projection.source, "database")
        self.assertTrue(projection.password_configured)

    async def test_update_config_retains_stored_password_on_empty_string(self) -> None:
        self.repo._row = _row(password="keep-me")

        await self.service.update_config(_valid_payload(password=""))

        self.assertEqual(self.repo.upsert_calls[0]["password"], "keep-me")

    async def test_update_config_without_existing_row_retains_empty_password(
        self,
    ) -> None:
        await self.service.update_config(_valid_payload(password=None))

        self.assertEqual(self.repo.upsert_calls[0]["password"], "")

    async def test_update_config_stores_new_password_when_provided(self) -> None:
        self.repo._row = _row(password="old-secret")

        await self.service.update_config(_valid_payload(password="new-secret"))

        self.assertEqual(self.repo.upsert_calls[0]["password"], "new-secret")

    async def test_update_config_clear_password_erases_stored_value(self) -> None:
        self.repo._row = _row(password="old-secret")

        projection = await self.service.update_config(
            _valid_payload(password=None, clear_password=True)
        )

        self.assertEqual(self.repo.upsert_calls[0]["password"], "")
        # DB 行密码清空后生效密码回落 env，投影反映 env 密码已配置
        self.assertTrue(projection.password_configured)
        self.assertNotIn("old-secret", projection.password_masked or "")

    async def test_update_config_rejects_invalid_port(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await self.service.update_config(_valid_payload(port=70000))

        self.assertIn("端口", str(ctx.exception))
        self.assertEqual(self.repo.upsert_calls, [])

    async def test_update_config_rejects_invalid_from_email(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await self.service.update_config(_valid_payload(from_email="not-an-email"))

        self.assertIn("发件邮箱", str(ctx.exception))
        self.assertEqual(self.repo.upsert_calls, [])

    async def test_update_config_empty_host_deletes_row_and_falls_back(self) -> None:
        self.repo._row = _row()

        projection = await self.service.update_config(_valid_payload(host="  "))

        self.assertEqual(self.repo.delete_calls, 1)
        self.assertEqual(self.repo.upsert_calls, [])
        self.assertIsNone(self.repo.get_smtp_settings())
        self.assertEqual(projection.source, "environment")

    async def test_send_test_email_uses_effective_database_config(self) -> None:
        self.repo._row = _row()

        result = await self.service.send_test_email("admin@example.test")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["to_email"], "admin@example.test")
        self.assertIsInstance(result["latency_ms"], int)
        # 生效配置来自 DB 行
        self.assertEqual(self.factory.configs[0].host, "db-smtp.example.test")
        self.assertEqual(self.factory.configs[0].source, "database")
        to_email, subject, body = self.transport.calls[0]
        self.assertEqual(to_email, "admin@example.test")
        self.assertIn("database", body)

    async def test_send_test_email_raises_when_unconfigured(self) -> None:
        service = SmtpConfigAdminService(
            self.repo,
            env_config=_env(SMTP_HOST=""),
            transport_factory=self.factory,
        )

        with self.assertRaises(SmtpNotConfiguredError) as ctx:
            await service.send_test_email("admin@example.test")

        self.assertIn("SMTP 未配置", ctx.exception.detail)
        self.assertEqual(self.transport.calls, [])

    async def test_send_test_email_wraps_delivery_error_with_safe_detail(self) -> None:
        self.repo._row = _row(password="super-secret-password")
        self.transport._error = SmtpDeliveryError("SMTPAuthenticationError")

        with self.assertRaises(SmtpTestDeliveryError) as ctx:
            await self.service.send_test_email("admin@example.test")

        self.assertIn("SMTPAuthenticationError", ctx.exception.detail)
        self.assertNotIn("super-secret-password", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
