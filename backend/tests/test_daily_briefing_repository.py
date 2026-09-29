from __future__ import annotations

import ast
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from backend.app.repositories.briefing_repository import BriefingContentRepository
from backend.app.services.briefing.composition import provide_daily_briefing_service
from backend.app.services.briefing.daily_briefing import DailyBriefingService


class DailyBriefingArchitectureTests(unittest.TestCase):
    def test_service_has_no_application_context_or_concrete_clients(self) -> None:
        import backend.app.services.briefing.daily_briefing as daily_briefing

        source = Path(daily_briefing.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }

        self.assertNotIn(
            "backend.app.repositories.application_repository_context",
            imported_modules,
        )
        self.assertNotIn("backend.app.repositories.milvus_repo", imported_modules)
        self.assertNotIn("backend.app.core.model_factory", imported_modules)


class DailyBriefingRepositoryTests(unittest.TestCase):
    def test_provider_wires_explicit_repositories_and_model(self) -> None:
        briefing_repository = MagicMock(spec=BriefingContentRepository)
        document_feed = MagicMock()
        snapshot_reader = MagicMock()
        model = MagicMock()
        repositories = SimpleNamespace(
            briefings=briefing_repository,
            documents=document_feed,
            rank_snapshots=snapshot_reader,
        )

        service = provide_daily_briefing_service(
            repositories=repositories,
            model=model,
        )

        self.assertIs(service._briefings, briefing_repository)
        self.assertIs(service._document_feed, document_feed)
        self.assertIs(service._rank_snapshots, snapshot_reader)
        self.assertIs(service._llm, model)

    def test_provider_requires_explicit_repositories(self) -> None:
        with self.assertRaises(TypeError):
            provide_daily_briefing_service(model=MagicMock())

    def test_explicit_provider_dependencies_forward_top_k(self) -> None:
        repositories = SimpleNamespace(
            briefings=MagicMock(spec=BriefingContentRepository),
            documents=MagicMock(),
            rank_snapshots=MagicMock(),
        )
        model = MagicMock()

        service = provide_daily_briefing_service(
            repositories=repositories,
            model=model,
            top_k=7,
        )

        self.assertIs(service._briefings, repositories.briefings)
        self.assertIs(service._document_feed, repositories.documents)
        self.assertIs(service._rank_snapshots, repositories.rank_snapshots)
        self.assertIs(service._llm, model)
        self.assertEqual(service._top_k, 7)

    def test_provider_reads_github_board_from_project_catalog_by_default(self) -> None:
        # 日报 GitHub 与首页 GitHub 榜同源：缺省注入项目库目录仓储（热度榜）。
        from backend.app.repositories.postgres_project_catalog import (
            PostgresProjectCatalogRepository,
        )

        repositories = SimpleNamespace(
            briefings=MagicMock(spec=BriefingContentRepository),
            documents=MagicMock(),
            rank_snapshots=MagicMock(),
        )
        default = provide_daily_briefing_service(
            repositories=repositories, model=MagicMock()
        )
        self.assertIsInstance(
            default._boards._github_hot, PostgresProjectCatalogRepository
        )

        github_hot = MagicMock()
        explicit = provide_daily_briefing_service(
            repositories=repositories, model=MagicMock(), github_hot_board=github_hot
        )
        self.assertIs(explicit._boards._github_hot, github_hot)

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
                force_regenerate=False,
            )
        )

        self.assertEqual([event["type"] for event in events], ["start", "content", "done"])
        self.assertEqual(events[1]["data"], "cached")
        self.assertEqual(events[2]["data"], {"briefing_id": 42})
        repository.get_briefing_by_date.assert_called_once_with("2026-07-22")
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

    @staticmethod
    def _service(repository: BriefingContentRepository) -> DailyBriefingService:
        return DailyBriefingService(
            briefing_repository=repository,
            document_feed=MagicMock(),
            rank_snapshot_reader=MagicMock(),
            github_hot_board=None,
            model=AsyncMock(),
        )

    @staticmethod
    def _collect(generator):
        async def collect():
            return [event async for event in generator]

        return asyncio.run(collect())


if __name__ == "__main__":
    unittest.main()
