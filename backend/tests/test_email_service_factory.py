from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.services import email_service
from backend.app.services.email.pool_config_provider import EffectiveEmailPoolConfig
from backend.app.services.email.pool_transport import EmailPoolTransport
from backend.app.services.email.smtp_config_provider import EffectiveSmtpConfig
from backend.app.services.email.smtp_transport import SmtpTransport
from backend.app.services.email_service import EmailService, build_email_service


class EmailServiceFactoryTests(unittest.TestCase):
    def test_build_email_service_maps_config_and_redis(self) -> None:
        redis_client = object()
        config = MagicMock(
            SMTP_HOST="smtp.example.test",
            SMTP_PORT=2465,
            SMTP_USERNAME="smtp-user",
            SMTP_PASSWORD="smtp-password",
            SMTP_FROM_EMAIL="sender@example.test",
            SMTP_FROM_NAME="AIGC Test",
            SMTP_USE_TLS=False,
        )
        service = object()

        with patch.object(email_service, "EmailService", return_value=service) as service_type:
            result = build_email_service(redis_client, config=config)

        self.assertIs(result, service)
        service_type.assert_called_once_with(
            redis_client=redis_client,
            smtp_host="smtp.example.test",
            smtp_port=2465,
            smtp_username="smtp-user",
            smtp_password="smtp-password",
            smtp_from_email="sender@example.test",
            smtp_from_name="AIGC Test",
            smtp_use_tls=False,
            otp_store=unittest.mock.ANY,
            renderer=unittest.mock.ANY,
            transport=unittest.mock.ANY,
        )
        kwargs = service_type.call_args.kwargs
        self.assertIs(kwargs["otp_store"]._redis, redis_client)
        self.assertEqual(kwargs["transport"]._host, "smtp.example.test")
        self.assertEqual(kwargs["transport"]._port, 2465)

    def test_build_email_service_has_no_io_side_effects(self) -> None:
        redis_client = MagicMock()
        config = MagicMock(
            SMTP_HOST="smtp.example.test",
            SMTP_PORT=465,
            SMTP_USERNAME="smtp-user",
            SMTP_PASSWORD="smtp-password",
            SMTP_FROM_EMAIL="sender@example.test",
            SMTP_FROM_NAME="AIGC Test",
            SMTP_USE_TLS=True,
        )

        with patch("aiosmtplib.send") as send:
            service = build_email_service(redis_client, config=config)

        self.assertIsInstance(service, EmailService)
        send.assert_not_called()
        redis_client.assert_not_called()

    def test_build_email_service_without_config_uses_runtime_provider(self) -> None:
        """生产默认路径：config=None 时经 smtp_config_provider 取热生效配置。"""
        redis_client = object()
        resolved = EffectiveSmtpConfig(
            host="db-smtp.example.test",
            port=587,
            username="db-user",
            password="db-password",
            from_email="db@example.test",
            from_name="DB Sender",
            use_tls=True,
            source="database",
        )
        service = object()

        with (
            patch.object(
                email_service, "resolve_smtp_config", return_value=resolved
            ) as resolver,
            patch.object(
                email_service, "EmailService", return_value=service
            ) as service_type,
        ):
            result = build_email_service(redis_client)

        self.assertIs(result, service)
        resolver.assert_called_once()
        kwargs = service_type.call_args.kwargs
        self.assertEqual(kwargs["smtp_host"], "db-smtp.example.test")
        self.assertEqual(kwargs["smtp_port"], 587)
        self.assertEqual(kwargs["smtp_username"], "db-user")
        self.assertEqual(kwargs["smtp_password"], "db-password")
        self.assertEqual(kwargs["smtp_from_email"], "db@example.test")
        self.assertEqual(kwargs["smtp_from_name"], "DB Sender")
        self.assertTrue(kwargs["smtp_use_tls"])
        self.assertEqual(kwargs["transport"]._host, "db-smtp.example.test")

    def test_build_email_service_config_none_reads_pool_from_provider(self) -> None:
        """config=None 路径：池配置经 pool_config_provider 解析（DB 覆盖 env），
        legacy 单 SMTP 并入兜底 entry。"""
        redis_client = object()
        resolved_smtp = EffectiveSmtpConfig(
            host="db-smtp.example.test",
            port=465,
            username="db-user",
            password="db-password",
            from_email="db@example.test",
            from_name="DB Sender",
            use_tls=True,
            source="database",
        )
        resolved_pool = EffectiveEmailPoolConfig(
            entries_json='[{"name":"brevo","host":"smtp-relay.brevo.test","priority":20}]',
            source="database",
        )

        with (
            patch.object(
                email_service, "resolve_smtp_config", return_value=resolved_smtp
            ),
            patch.object(
                email_service, "resolve_email_pool_config", return_value=resolved_pool
            ) as pool_resolver,
        ):
            service = build_email_service(redis_client)

        pool_resolver.assert_called_once()
        transport = service._transport
        self.assertIsInstance(transport, EmailPoolTransport)
        names = [entry.name for entry in transport._entries]
        self.assertEqual(names, ["brevo", "legacy-smtp"])
        # legacy 兜底 priority 恒大于池内最大 priority
        self.assertGreater(
            transport._entries[-1].priority, transport._entries[0].priority
        )
        # 池 entry 缺省 from_* 继承 legacy 发件身份
        self.assertEqual(transport._entries[0].from_email, "db@example.test")

    def test_build_email_service_config_none_pool_unconfigured_keeps_single_smtp(
        self,
    ) -> None:
        """池未配置（DB 与 env 均无）时保持改造前单 SMTP 行为。"""
        redis_client = object()
        resolved_smtp = EffectiveSmtpConfig(
            host="db-smtp.example.test",
            port=465,
            username="db-user",
            password="db-password",
            from_email="db@example.test",
            from_name="DB Sender",
            use_tls=True,
            source="database",
        )
        resolved_pool = EffectiveEmailPoolConfig(entries_json="", source="unconfigured")

        with (
            patch.object(
                email_service, "resolve_smtp_config", return_value=resolved_smtp
            ),
            patch.object(
                email_service, "resolve_email_pool_config", return_value=resolved_pool
            ),
        ):
            service = build_email_service(redis_client)

        self.assertIsInstance(service._transport, SmtpTransport)
        self.assertEqual(service._transport._host, "db-smtp.example.test")


if __name__ == "__main__":
    unittest.main()
