from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.core import scheduler


class SchedulerEmailServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_briefing_uses_factory_without_redis(self) -> None:
        repository = MagicMock()
        repository.get_active_subscribers.return_value = [
            {"email": "subscriber@example.com"}
        ]
        email_service = MagicMock()
        email_service.send_briefing = AsyncMock()

        with (
            patch(
                "backend.app.repositories.mysql_repo.MySQLRepository",
                return_value=repository,
            ),
            patch(
                "backend.app.services.email_service.build_email_service",
                return_value=email_service,
            ) as factory,
        ):
            sent = await scheduler._send_briefing_to_subscribers(
                source="github",
                period="daily",
                date_str="2026-07-22",
                content="briefing content",
            )

        self.assertEqual(sent, 1)
        repository.get_active_subscribers.assert_called_once_with(
            source="github",
            period="daily",
        )
        factory.assert_called_once_with(None)
        email_service.send_briefing.assert_awaited_once_with(
            to_email="subscriber@example.com",
            briefing_content="briefing content",
            source="github",
            period="daily",
            date_str="2026-07-22",
        )


if __name__ == "__main__":
    unittest.main()
