"""EmailPoolConfigAdminService 的读写投影与测试投递语义契约测试。"""

from __future__ import annotations

import dataclasses
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from backend.app.repositories.email_pool_settings_repository import EmailPoolSettings
from backend.app.services.email.pool_config_provider import (
    configure_email_pool_settings_reader,
    reset_email_pool_config_provider,
)
from backend.app.services.email.smtp_config_provider import (
    reset_smtp_config_provider,
)
from backend.app.services.email.smtp_transport import SmtpDeliveryError
from backend.app.services.email_pool_config_admin import (
    EmailPoolConfigAdminService,
    EmailPoolEntryProjection,
    EmailPoolNotConfiguredError,
    EmailPoolTestDeliveryError,
)

_DB_JSON = json.dumps(
    [
        {
            "name": "brevo",
            "host": "smtp-relay.brevo.test",
            "port": 587,
            "username": "db-user",
            "password": "db-secret-key",
            "from_email": "",
            "from_name": "",
            "use_tls": True,
            "daily_limit": 280,
            "monthly_limit": 8500,
            "priority": 20,
        }
    ],
    ensure_ascii=False,
)


def _env(**overrides):
    values = {
        "EMAIL_POOL_JSON": "",
        "SMTP_HOST": "legacy-smtp.example.test",
        "SMTP_PORT": 465,
        "SMTP_USERNAME": "legacy-user",
        "SMTP_PASSWORD": "legacy-password",
        "SMTP_FROM_EMAIL": "noreply@example.test",
        "SMTP_FROM_NAME": "AIGC Test",
        "SMTP_USE_TLS": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeEmailPoolSettingsRepository:
    def __init__(self, row: EmailPoolSettings | None = None) -> None:
        self._row = row
        self.upsert_calls: list[dict] = []
        self.delete_calls = 0

    def get_email_pool_settings(self) -> EmailPoolSettings | None:
        return self._row

    def upsert_email_pool_settings(self, *, entries_json: str) -> EmailPoolSettings:
        self.upsert_calls.append({"entries_json": entries_json})
        self._row = EmailPoolSettings(
            entries_json=entries_json,
            updated_at=datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc),
        )
        return self._row

    def delete_email_pool_settings(self) -> int:
        self.delete_calls += 1
        had_row = self._row is not None
        self._row = None
        return 1 if had_row else 0


class FakePoolTransport:
    def __init__(self, provider: str = "brevo", error: SmtpDeliveryError | None = None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self._provider = provider
        self._error = error

    async def send_plain(self, to_email: str, subject: str, body: str) -> str:
        self.calls.append((to_email, subject, body))
        if self._error is not None:
            raise self._error
        return self._provider


class FakePoolTransportFactory:
    """记录收到的 entry 列表，返回预置 pool transport。"""

    def __init__(self, transport: FakePoolTransport) -> None:
        self._transport = transport
        self.entries_calls = []

    def __call__(self, entries):
        self.entries_calls.append(entries)
        return self._transport


def _valid_entry(**overrides) -> dict:
    entry = {
        "name": "brevo",
        "host": "smtp-relay.brevo.test",
        "port": 587,
        "username": "user",
        "password": None,
        "clear_password": False,
        "from_email": "",
        "from_name": "",
        "use_tls": True,
        "daily_limit": 280,
        "monthly_limit": 8500,
        "priority": 20,
    }
    entry.update(overrides)
    return entry


class EmailPoolConfigAdminServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.repo = FakeEmailPoolSettingsRepository()
        # 对齐生产 lifespan：admin 服务的投影经 provider 读 DB 行
        configure_email_pool_settings_reader(self.repo)
        self.addCleanup(reset_email_pool_config_provider)
        self.addCleanup(reset_smtp_config_provider)
        self.transport = FakePoolTransport()
        self.factory = FakePoolTransportFactory(self.transport)
        self.service = EmailPoolConfigAdminService(
            self.repo,
            env_config=_env(),
            transport_factory=self.factory,
        )

    def _saved_entries(self) -> list[dict]:
        return json.loads(self.repo.upsert_calls[-1]["entries_json"])

    async def test_get_config_reflects_database_row_without_plaintext(self) -> None:
        self.repo._row = EmailPoolSettings(
            entries_json=_DB_JSON,
            updated_at=datetime(2026, 8, 14, 10, 0, tzinfo=timezone.utc),
        )

        projection = await self.service.get_config()

        self.assertEqual(projection.source, "database")
        self.assertEqual(len(projection.entries), 1)
        entry = projection.entries[0]
        self.assertEqual(entry.name, "brevo")
        self.assertTrue(entry.password_configured)
        self.assertIsNotNone(entry.password_masked)
        self.assertNotIn("db-secret-key", entry.password_masked)
        # 空 from_* 继承单 SMTP 生效发件身份
        self.assertEqual(entry.from_email, "noreply@example.test")
        self.assertEqual(entry.from_name, "AIGC Test")
        self.assertEqual(projection.updated_at, "2026-08-14T10:00:00+00:00")

    async def test_get_config_falls_back_to_env_when_row_missing(self) -> None:
        service = EmailPoolConfigAdminService(
            self.repo,
            env_config=_env(
                EMAIL_POOL_JSON='[{"name":"resend","host":"smtp.resend.test"}]'
            ),
            transport_factory=self.factory,
        )

        projection = await service.get_config()

        self.assertEqual(projection.source, "environment")
        self.assertEqual([entry.name for entry in projection.entries], ["resend"])
        self.assertIsNone(projection.updated_at)

    async def test_projection_never_carries_plaintext_password_field(self) -> None:
        field_names = {
            field.name for field in dataclasses.fields(EmailPoolEntryProjection)
        }
        self.assertNotIn("password", field_names)

    async def test_update_config_retains_password_by_entry_name(self) -> None:
        self.repo._row = EmailPoolSettings(entries_json=_DB_JSON)

        await self.service.update_config({"entries": [_valid_entry(password=None)]})

        self.assertEqual(self._saved_entries()[0]["password"], "db-secret-key")

    async def test_update_config_stores_new_password_when_provided(self) -> None:
        self.repo._row = EmailPoolSettings(entries_json=_DB_JSON)

        await self.service.update_config(
            {"entries": [_valid_entry(password="new-key")]}
        )

        self.assertEqual(self._saved_entries()[0]["password"], "new-key")

    async def test_update_config_clear_password_erases_stored_value(self) -> None:
        self.repo._row = EmailPoolSettings(entries_json=_DB_JSON)

        await self.service.update_config(
            {"entries": [_valid_entry(password=None, clear_password=True)]}
        )

        self.assertEqual(self._saved_entries()[0]["password"], "")

    async def test_update_config_rename_loses_stored_password(self) -> None:
        # 文档化语义：entry 以 name 为键，改名视为新 entry，不继承密码
        self.repo._row = EmailPoolSettings(entries_json=_DB_JSON)

        await self.service.update_config(
            {"entries": [_valid_entry(name="brevo-renamed", password=None)]}
        )

        self.assertEqual(self._saved_entries()[0]["password"], "")

    async def test_update_config_new_entry_without_password_stores_empty(self) -> None:
        await self.service.update_config({"entries": [_valid_entry(password=None)]})

        self.assertEqual(self._saved_entries()[0]["password"], "")

    async def test_update_config_canonicalizes_and_sorts_by_priority(self) -> None:
        projection = await self.service.update_config(
            {
                "entries": [
                    _valid_entry(name="mailjet", priority=30, password="mj-key"),
                    _valid_entry(name="resend", host="smtp.resend.test", priority=10),
                ]
            }
        )

        saved = self._saved_entries()
        self.assertEqual([entry["name"] for entry in saved], ["resend", "mailjet"])
        self.assertEqual(
            sorted(saved[0].keys()),
            [
                "daily_limit",
                "from_email",
                "from_name",
                "host",
                "monthly_limit",
                "name",
                "password",
                "port",
                "priority",
                "use_tls",
                "username",
            ],
        )
        self.assertEqual(projection.source, "database")
        self.assertEqual(
            [entry.name for entry in projection.entries], ["resend", "mailjet"]
        )

    async def test_update_config_empty_entries_deletes_row_and_falls_back(self) -> None:
        self.repo._row = EmailPoolSettings(entries_json=_DB_JSON)

        projection = await self.service.update_config({"entries": []})

        self.assertEqual(self.repo.delete_calls, 1)
        self.assertEqual(self.repo.upsert_calls, [])
        self.assertIsNone(self.repo.get_email_pool_settings())
        self.assertEqual(projection.source, "unconfigured")

    async def test_update_config_rejects_duplicate_names(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await self.service.update_config(
                {"entries": [_valid_entry(), _valid_entry(host="smtp.other.test")]}
            )

        self.assertIn("重复", str(ctx.exception))
        self.assertEqual(self.repo.upsert_calls, [])

    async def test_update_config_rejects_ssrf_hosts(self) -> None:
        for bad_host in ("127.0.0.1", "localhost", "169.254.169.254"):
            with self.assertRaises(ValueError):
                await self.service.update_config(
                    {"entries": [_valid_entry(host=bad_host)]}
                )
        self.assertEqual(self.repo.upsert_calls, [])

    async def test_update_config_rejects_invalid_port_and_limits(self) -> None:
        with self.assertRaises(ValueError):
            await self.service.update_config({"entries": [_valid_entry(port=70000)]})
        with self.assertRaises(ValueError):
            await self.service.update_config(
                {"entries": [_valid_entry(daily_limit="abc")]}
            )
        self.assertEqual(self.repo.upsert_calls, [])

    async def test_update_config_rejects_invalid_from_email(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await self.service.update_config(
                {"entries": [_valid_entry(from_email="not-an-email")]}
            )

        self.assertIn("发件邮箱", str(ctx.exception))

    async def test_send_test_email_through_pool_reports_provider(self) -> None:
        self.repo._row = EmailPoolSettings(entries_json=_DB_JSON)

        result = await self.service.send_test_email("admin@example.test")

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["provider"], "brevo")
        self.assertEqual(result["to_email"], "admin@example.test")
        self.assertIsInstance(result["latency_ms"], int)
        # 测试链路与生产一致：池 entry 在前，legacy-smtp 兜底并入
        names = [entry.name for entry in self.factory.entries_calls[0]]
        self.assertEqual(names, ["brevo", "legacy-smtp"])
        to_email, _, body = self.transport.calls[0]
        self.assertEqual(to_email, "admin@example.test")
        self.assertIn("database", body)

    async def test_send_test_email_without_legacy_smtp_sends_pool_only(self) -> None:
        self.repo._row = EmailPoolSettings(entries_json=_DB_JSON)
        service = EmailPoolConfigAdminService(
            self.repo,
            env_config=_env(SMTP_HOST=""),
            transport_factory=self.factory,
        )

        await service.send_test_email("admin@example.test")

        names = [entry.name for entry in self.factory.entries_calls[0]]
        self.assertEqual(names, ["brevo"])

    async def test_send_test_email_raises_when_unconfigured(self) -> None:
        service = EmailPoolConfigAdminService(
            self.repo,
            env_config=_env(SMTP_HOST=""),
            transport_factory=self.factory,
        )

        with self.assertRaises(EmailPoolNotConfiguredError) as ctx:
            await service.send_test_email("admin@example.test")

        self.assertIn("邮件池未配置", ctx.exception.detail)
        self.assertEqual(self.transport.calls, [])

    async def test_send_test_email_unconfigured_pool_stays_400_with_legacy_smtp(
        self,
    ) -> None:
        # 文档化语义：legacy-smtp 只作为已有池的兜底并入，不单独成池——
        # 池未配置时即返回 400，单 SMTP 链路用 SMTP 面板自己的测试按钮验证
        with self.assertRaises(EmailPoolNotConfiguredError) as ctx:
            await self.service.send_test_email("admin@example.test")

        self.assertIn("邮件池未配置", ctx.exception.detail)
        self.assertEqual(self.transport.calls, [])

    async def test_send_test_email_delivery_failure_maps_502_error(self) -> None:
        self.repo._row = EmailPoolSettings(entries_json=_DB_JSON)
        failing = FakePoolTransport(error=SmtpDeliveryError("PoolExhausted"))
        service = EmailPoolConfigAdminService(
            self.repo,
            env_config=_env(),
            transport_factory=FakePoolTransportFactory(failing),
        )

        with self.assertRaises(EmailPoolTestDeliveryError) as ctx:
            await service.send_test_email("admin@example.test")

        self.assertIn("全部服务商", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
