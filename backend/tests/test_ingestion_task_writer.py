from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.repositories.task_repository import IngestionTaskWriter
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

    def test_default_writer_reuses_data_repository(self) -> None:
        repository = MagicMock(spec=IngestionTaskWriter)

        with (
            patch(
                "backend.app.services.ingestion.pipeline.MySQLRepository",
                return_value=repository,
            ),
            patch.object(IngestionOrchestrator, "_CRAWLER_CLASSES", []),
        ):
            orchestrator = IngestionOrchestrator()

        self.assertIs(orchestrator.db, repository)
        self.assertIs(orchestrator.task_writer, repository)

    def test_injected_writer_keeps_data_repository_separate(self) -> None:
        repository = MagicMock()
        writer = MagicMock(spec=IngestionTaskWriter)

        with (
            patch(
                "backend.app.services.ingestion.pipeline.MySQLRepository",
                return_value=repository,
            ),
            patch.object(IngestionOrchestrator, "_CRAWLER_CLASSES", []),
        ):
            orchestrator = IngestionOrchestrator(task_writer=writer)

        self.assertIs(orchestrator.db, repository)
        self.assertIs(orchestrator.task_writer, writer)


if __name__ == "__main__":
    unittest.main()
