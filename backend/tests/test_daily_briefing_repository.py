from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.repositories.briefing_repository import BriefingContentRepository
from backend.app.services.briefing.daily_briefing import DailyBriefingService


class DailyBriefingRepositoryTests(unittest.TestCase):
    def test_default_briefing_repository_uses_mysql_component(self) -> None:
        briefing_repository = MagicMock(spec=BriefingContentRepository)
        mysql_repository = MagicMock(briefings=briefing_repository)

        with patch(
            "backend.app.services.briefing.daily_briefing.get_chat_model",
            return_value=MagicMock(),
        ):
            service = DailyBriefingService(mysql_repo=mysql_repository)

        self.assertIs(service._db, mysql_repository)
        self.assertIs(service._briefings, briefing_repository)

    def test_injected_briefing_repository_remains_separate(self) -> None:
        briefing_repository = MagicMock(spec=BriefingContentRepository)
        mysql_repository = MagicMock()

        with patch(
            "backend.app.services.briefing.daily_briefing.get_chat_model",
            return_value=MagicMock(),
        ):
            service = DailyBriefingService(
                mysql_repo=mysql_repository,
                briefing_repository=briefing_repository,
            )

        self.assertIs(service._db, mysql_repository)
        self.assertIs(service._briefings, briefing_repository)

    def test_cached_stream_uses_briefing_repository_and_preserves_events(self) -> None:
        repository = MagicMock(spec=BriefingContentRepository)
        repository.get_briefing_by_date.return_value = {
            "id": 42,
            "content": "cached",
        }
        service = self._service(repository)

        events = self._collect(
            service.stream_generate(
                target_date="2026-07-22",
                source="all",
                period="daily",
                force_regenerate=False,
            )
        )

        self.assertEqual([event["type"] for event in events], ["start", "content", "done"])
        self.assertEqual(events[1]["data"], "cached")
        self.assertEqual(events[2]["data"], {"briefing_id": 42})
        repository.get_briefing_by_date.assert_called_once_with("2026-07-22_daily")
        repository.save_briefing.assert_not_called()

    def test_force_regenerate_does_not_read_briefing_cache(self) -> None:
        repository = MagicMock(spec=BriefingContentRepository)
        service = self._service(repository)
        service._db.get_snapshot_documents.return_value = []

        events = self._collect(
            service.stream_generate(
                target_date="2026-07-22",
                force_regenerate=True,
            )
        )

        repository.get_briefing_by_date.assert_not_called()
        repository.save_briefing.assert_not_called()
        self.assertEqual(events[-1]["type"], "done")

    def test_history_uses_briefing_repository(self) -> None:
        repository = MagicMock(spec=BriefingContentRepository)
        repository.list_briefings.return_value = [{"id": 42}]
        service = self._service(repository)

        self.assertEqual(service.get_history(limit=7), [{"id": 42}])
        repository.list_briefings.assert_called_once_with(limit=7)

    @staticmethod
    def _service(repository: BriefingContentRepository) -> DailyBriefingService:
        mysql_repository = MagicMock()
        with patch(
            "backend.app.services.briefing.daily_briefing.get_chat_model",
            return_value=AsyncMock(),
        ):
            return DailyBriefingService(
                mysql_repo=mysql_repository,
                briefing_repository=repository,
            )

    @staticmethod
    def _collect(generator):
        async def collect():
            return [event async for event in generator]

        return asyncio.run(collect())


if __name__ == "__main__":
    unittest.main()
