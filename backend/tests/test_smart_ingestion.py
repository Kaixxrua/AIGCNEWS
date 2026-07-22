from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from backend.app.repositories.task_repository import LatestTaskReader
from backend.app.services.ingestion.pipeline import (
    run_smart_ingestion,
    should_run_smart_ingestion,
)


class SmartIngestionDecisionTests(unittest.TestCase):
    def test_runs_without_latest_task(self) -> None:
        self.assertTrue(should_run_smart_ingestion(None, date(2026, 7, 22)))

    def test_runs_after_failed_task(self) -> None:
        self.assertTrue(
            should_run_smart_ingestion(
                {"status": "failed", "started_at": "2026-07-22 08:00:00"},
                date(2026, 7, 22),
            )
        )

    def test_runs_after_older_successful_task(self) -> None:
        self.assertTrue(
            should_run_smart_ingestion(
                {"status": "success", "started_at": "2026-07-21 08:00:00"},
                date(2026, 7, 22),
            )
        )

    def test_skips_after_successful_task_today(self) -> None:
        self.assertFalse(
            should_run_smart_ingestion(
                {"status": "success", "started_at": "2026-07-22 08:00:00"},
                date(2026, 7, 22),
            )
        )

    def test_skips_after_successful_task_from_future_date(self) -> None:
        self.assertFalse(
            should_run_smart_ingestion(
                {"status": "success", "started_at": "2026-07-23 08:00:00"},
                date(2026, 7, 22),
            )
        )

    def test_runs_when_started_at_is_missing_or_invalid(self) -> None:
        for started_at in (None, "", "invalid", date(2026, 7, 22)):
            with self.subTest(started_at=started_at):
                self.assertTrue(
                    should_run_smart_ingestion(
                        {"status": "success", "started_at": started_at},
                        date(2026, 7, 22),
                    )
                )


class SmartIngestionInjectionTests(unittest.TestCase):
    def test_injected_reader_can_skip_runner(self) -> None:
        reader = MagicMock(spec=LatestTaskReader)
        reader.get_latest_task.return_value = {
            "id": 42,
            "status": "success",
            "started_at": "2026-07-22 08:00:00",
        }
        runner = MagicMock()

        with patch(
            "backend.app.services.ingestion.pipeline.date"
        ) as date_module:
            date_module.today.return_value = date(2026, 7, 22)
            date_module.fromisoformat.side_effect = date.fromisoformat
            run_smart_ingestion(7, reader=reader, runner=runner)

        reader.get_latest_task.assert_called_once_with()
        runner.assert_not_called()

    def test_injected_reader_and_runner_execute_requested_limit(self) -> None:
        reader = MagicMock(spec=LatestTaskReader)
        reader.get_latest_task.return_value = None
        runner = MagicMock()

        run_smart_ingestion(7, reader=reader, runner=runner)

        runner.assert_called_once_with(7)

    def test_reader_failure_is_fail_open(self) -> None:
        reader = MagicMock(spec=LatestTaskReader)
        reader.get_latest_task.side_effect = RuntimeError("lookup failed")
        runner = MagicMock()

        run_smart_ingestion(7, reader=reader, runner=runner)

        runner.assert_called_once_with(7)

    def test_runner_failure_is_swallowed(self) -> None:
        reader = MagicMock(spec=LatestTaskReader)
        reader.get_latest_task.return_value = None
        runner = MagicMock(side_effect=RuntimeError("run failed"))

        self.assertIsNone(run_smart_ingestion(7, reader=reader, runner=runner))

    def test_injected_reader_avoids_default_repository(self) -> None:
        reader = MagicMock(spec=LatestTaskReader)
        reader.get_latest_task.return_value = None
        runner = MagicMock()

        with patch(
            "backend.app.services.ingestion.pipeline.MySQLRepository"
        ) as repository_type:
            run_smart_ingestion(7, reader=reader, runner=runner)

        repository_type.assert_not_called()


if __name__ == "__main__":
    unittest.main()
