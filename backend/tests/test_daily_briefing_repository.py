from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.repositories.briefing_repository import BriefingContentRepository
from backend.app.services.briefing.daily_briefing import DailyBriefingService


class DailyBriefingRepositoryTests(unittest.TestCase):
    def test_default_repositories_use_application_components(self) -> None:
        briefing_repository = MagicMock(spec=BriefingContentRepository)
        document_feed = MagicMock()
        snapshot_reader = MagicMock()
        repositories = SimpleNamespace(
            briefings=briefing_repository,
            documents=document_feed,
            rank_snapshots=snapshot_reader,
        )

        with (
            patch(
                "backend.app.services.briefing.daily_briefing.get_configured_application_repositories",
                return_value=repositories,
            ) as repository_provider,
            patch(
                "backend.app.services.briefing.daily_briefing.get_chat_model",
                return_value=MagicMock(),
            ),
        ):
            service = DailyBriefingService()

        repository_provider.assert_called_once_with()
        self.assertIs(service._briefings, briefing_repository)
        self.assertIs(service._document_feed, document_feed)
        self.assertIs(service._rank_snapshots, snapshot_reader)

    def test_fully_injected_repositories_avoid_application_context(self) -> None:
        briefing_repository = MagicMock(spec=BriefingContentRepository)
        document_feed = MagicMock()
        snapshot_reader = MagicMock()

        with (
            patch(
                "backend.app.services.briefing.daily_briefing.get_configured_application_repositories"
            ) as repository_provider,
            patch(
                "backend.app.services.briefing.daily_briefing.get_chat_model",
                return_value=MagicMock(),
            ),
        ):
            service = DailyBriefingService(
                briefing_repository=briefing_repository,
                document_feed=document_feed,
                rank_snapshot_reader=snapshot_reader,
            )

        repository_provider.assert_not_called()
        self.assertIs(service._briefings, briefing_repository)
        self.assertIs(service._document_feed, document_feed)
        self.assertIs(service._rank_snapshots, snapshot_reader)

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
        service._rank_snapshots.get_snapshot_documents.return_value = []

        events = self._collect(
            service.stream_generate(
                target_date="2026-07-22",
                force_regenerate=True,
            )
        )

        repository.get_briefing_by_date.assert_not_called()
        repository.save_briefing.assert_not_called()
        self.assertEqual(events[-1]["type"], "done")

    def test_reads_delegate_to_briefing_repository(self) -> None:
        repository = MagicMock(spec=BriefingContentRepository)
        repository.list_briefings.return_value = [{"id": 42}]
        repository.get_briefing.return_value = {"id": 42, "content": "briefing"}
        service = self._service(repository)

        self.assertEqual(service.get_history(limit=7), [{"id": 42}])
        self.assertEqual(
            service.get_briefing(42),
            {"id": 42, "content": "briefing"},
        )
        repository.list_briefings.assert_called_once_with(limit=7)
        repository.get_briefing.assert_called_once_with(42)

    @staticmethod
    def _service(repository: BriefingContentRepository) -> DailyBriefingService:
        with patch(
            "backend.app.services.briefing.daily_briefing.get_chat_model",
            return_value=AsyncMock(),
        ):
            return DailyBriefingService(
                briefing_repository=repository,
                document_feed=MagicMock(),
                rank_snapshot_reader=MagicMock(),
            )

    @staticmethod
    def _collect(generator):
        async def collect():
            return [event async for event in generator]

        return asyncio.run(collect())


if __name__ == "__main__":
    unittest.main()
