from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Request

from backend.app.api import routes_report
from backend.app.repositories.briefing_repository import BriefingReader
from backend.app.services.email_service import EmailService


class ReportEmailServiceWiringTests(unittest.TestCase):
    def test_get_email_service_passes_application_redis_to_factory(self) -> None:
        app = FastAPI()
        redis_client = object()
        app.state.redis = redis_client
        request = MagicMock(spec=Request)
        request.app = app
        service = MagicMock(spec=EmailService)

        with patch.object(
            routes_report,
            "build_email_service",
            return_value=service,
        ) as factory:
            result = routes_report._get_email_service(request)

        self.assertIs(result, service)
        factory.assert_called_once_with(redis_client)


class ReportBriefingRepositoryTests(unittest.TestCase):
    def test_latest_uses_repository_and_preserves_cache_key(self) -> None:
        repository = MagicMock(spec=BriefingReader)
        repository.get_briefing_by_date.return_value = {
            "id": 42,
            "date": "2026-07-20_github_weekly",
            "content": "cached",
        }

        result = asyncio.run(
            routes_report.get_latest_briefing(
                source="github",
                period="weekly",
                date="2026-07-22",
                repository=repository,
            )
        )

        repository.get_briefing_by_date.assert_called_once_with(
            "2026-07-20_github_weekly"
        )
        self.assertEqual(
            result,
            {
                "id": 42,
                "date": "2026-07-20_github_weekly",
                "content": "cached",
                "source": "github",
                "period": "weekly",
                "cache_key": "2026-07-20_github_weekly",
            },
        )

    def test_latest_missing_preserves_response(self) -> None:
        repository = MagicMock(spec=BriefingReader)
        repository.get_briefing_by_date.return_value = None

        response = asyncio.run(
            routes_report.get_latest_briefing(
                source="invalid",
                period="invalid",
                date="2026-07-22",
                repository=repository,
            )
        )

        repository.get_briefing_by_date.assert_called_once_with("2026-07-22_daily")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.body.decode(),
            '{"detail":"对应简报尚未生成","cache_key":"2026-07-22_daily"}',
        )

    def test_history_uses_repository(self) -> None:
        repository = MagicMock(spec=BriefingReader)
        repository.list_briefings.return_value = [{"id": 42}]

        result = asyncio.run(
            routes_report.list_briefings(limit=7, repository=repository)
        )

        self.assertEqual(result, {"items": [{"id": 42}], "total": 1})
        repository.list_briefings.assert_called_once_with(limit=7)

    def test_email_helper_uses_explicit_repository(self) -> None:
        repository = MagicMock(spec=BriefingReader)
        repository.get_briefing_by_date.return_value = {"content": "cached"}
        request = MagicMock(spec=Request)
        email_service = MagicMock(spec=EmailService)
        email_service.send_briefing = AsyncMock()

        with patch.object(
            routes_report,
            "_get_email_service",
            return_value=email_service,
        ):
            result = asyncio.run(
                routes_report._send_cached_briefing_to_email(
                    request=request,
                    repository=repository,
                    email="reader@example.com",
                    source="all",
                    period="monthly",
                    date_str="2026-07-22",
                )
            )

        self.assertEqual(result, "2026-07-01")
        repository.get_briefing_by_date.assert_called_once_with(
            "2026-07-01_monthly"
        )
        email_service.send_briefing.assert_awaited_once_with(
            to_email="reader@example.com",
            briefing_content="cached",
            source="all",
            period="monthly",
            date_str="2026-07-01",
        )


if __name__ == "__main__":
    unittest.main()
