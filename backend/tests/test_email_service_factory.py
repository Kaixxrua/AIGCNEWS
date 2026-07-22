from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.services import email_service
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
        )

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


if __name__ == "__main__":
    unittest.main()
