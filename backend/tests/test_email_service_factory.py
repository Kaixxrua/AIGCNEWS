from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.services import email_service
from backend.app.services.email.smtp_config_provider import EffectiveSmtpConfig
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


if __name__ == "__main__":
    unittest.main()
