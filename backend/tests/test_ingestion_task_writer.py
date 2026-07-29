from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.repositories.task_repository import IngestionTaskWriter
from backend.app.services.ingestion.base_crawler import CrawlResult
from backend.app.services.ingestion.pipeline import IngestionOrchestrator


class IngestionTaskWriterTests(unittest.TestCase):
    def test_injected_writer_receives_task_lifecycle_calls(self) -> None:
        writer = MagicMock(spec=IngestionTaskWriter)
        writer.create_task.return_value = 42
        orchestrator = IngestionOrchestrator.__new__(IngestionOrchestrator)
        orchestrator.task_writer = writer

        task_id = orchestrator._create_task("single:github")
        orchestrator._finish_task(
            task_id,
            status="failed",
            error_msg="sentinel",
            item_count=3,
        )

        self.assertEqual(task_id, 42)
        writer.create_task.assert_called_once_with("single:github")
        writer.finish_task.assert_called_once_with(
            42,
            status="failed",
            error_msg="sentinel",
            item_count=3,
        )

    def test_default_writer_uses_data_repository_task_component(self) -> None:
        writer = MagicMock(spec=IngestionTaskWriter)
        repository = MagicMock(ingestion_tasks=writer)

        with (
            patch(
                "backend.app.services.ingestion.pipeline.get_configured_application_repositories",
                return_value=repository,
            ),
            patch.object(IngestionOrchestrator, "_CRAWLER_CLASSES", []),
        ):
            orchestrator = IngestionOrchestrator()

        self.assertIs(orchestrator.repositories, repository)
        self.assertIs(orchestrator.task_writer, writer)

    def test_injected_writer_keeps_data_repository_separate(self) -> None:
        repository = MagicMock()
        writer = MagicMock(spec=IngestionTaskWriter)

        with patch.object(IngestionOrchestrator, "_CRAWLER_CLASSES", []):
            orchestrator = IngestionOrchestrator(
                task_writer=writer,
                repositories=repository,
            )

        self.assertIs(orchestrator.repositories, repository)
        self.assertIs(orchestrator.task_writer, writer)

    def test_run_single_source_uses_writer_on_success(self) -> None:
        orchestrator, writer, repository = self._orchestrator_with_crawler()
        orchestrator._enrich_and_ingest = AsyncMock(return_value=3)

        with patch(
            "backend.app.services.ingestion.pipeline._clear_dashboard_cache_safely",
            new=AsyncMock(),
        ):
            result = self._run(orchestrator.run_single_source("news", ["daily"]))

        self.assertEqual(result, {"news": 3, "ingested_total": 3})
        writer.create_task.assert_called_once_with("single:news")
        writer.finish_task.assert_called_once_with(
            42,
            status="success",
            error_msg=None,
            item_count=3,
        )
        repository.create_task.assert_not_called()
        repository.finish_task.assert_not_called()

    def test_run_single_source_uses_writer_on_failure(self) -> None:
        orchestrator, writer, repository = self._orchestrator_with_crawler()
        error = RuntimeError("sentinel")
        orchestrator._enrich_and_ingest = AsyncMock(side_effect=error)

        with self.assertRaises(RuntimeError) as context:
            self._run(orchestrator.run_single_source("news", ["daily"]))

        self.assertIs(context.exception, error)
        writer.finish_task.assert_called_once_with(
            42,
            status="failed",
            error_msg="sentinel",
            item_count=0,
        )
        repository.finish_task.assert_not_called()

    def test_run_all_uses_writer_on_success(self) -> None:
        orchestrator, writer, repository = self._orchestrator_with_crawler()
        orchestrator._enrich_and_ingest = AsyncMock(return_value=2)

        with patch(
            "backend.app.services.ingestion.pipeline._clear_dashboard_cache_safely",
            new=AsyncMock(),
        ):
            result = self._run(orchestrator.run_all())

        self.assertEqual(result["ingested_total"], 2)
        writer.create_task.assert_called_once_with("multi_source_ingest")
        writer.finish_task.assert_called_once_with(
            42,
            status="success",
            error_msg=None,
            item_count=2,
        )
        repository.create_task.assert_not_called()
        repository.finish_task.assert_not_called()

    def test_run_all_uses_writer_on_failure(self) -> None:
        orchestrator, writer, repository = self._orchestrator_with_crawler()
        error = RuntimeError("sentinel")
        orchestrator._enrich_and_ingest = AsyncMock(side_effect=error)

        with self.assertRaises(RuntimeError) as context:
            self._run(orchestrator.run_all())

        self.assertIs(context.exception, error)
        writer.finish_task.assert_called_once_with(
            42,
            status="failed",
            error_msg="sentinel",
            item_count=0,
        )
        repository.finish_task.assert_not_called()

    @staticmethod
    def _run(coroutine):
        import asyncio

        return asyncio.run(coroutine)

    @staticmethod
    def _orchestrator_with_crawler():
        repository = MagicMock()
        writer = MagicMock(spec=IngestionTaskWriter)
        writer.create_task.return_value = 42
        crawler = MagicMock()
        crawler.supported_periods = ["daily"]
        crawler.fetch = AsyncMock(
            return_value=CrawlResult(
                source="news",
                source_channel="news_daily",
                snapshot_date="2026-07-22",
                period="daily",
                items=[{"title": "Item"}],
            )
        )
        orchestrator = IngestionOrchestrator.__new__(IngestionOrchestrator)
        orchestrator.limit = 25
        orchestrator.top_n = 10
        orchestrator.target_date = None
        orchestrator.snapshot_date = "2026-07-22"
        orchestrator.repositories = repository
        orchestrator.documents = repository.documents
        orchestrator.rank_snapshots = repository.rank_snapshots
        orchestrator.github_ingestion = repository.github_ingestion
        orchestrator.task_writer = writer
        orchestrator._crawlers = {"news": crawler}
        orchestrator._start_arxiv_pdf_background = MagicMock()
        return orchestrator, writer, repository


if __name__ == "__main__":
    unittest.main()
