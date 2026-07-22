from __future__ import annotations

import unittest
from datetime import date

from backend.app.services.ingestion.pipeline import should_run_smart_ingestion


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


if __name__ == "__main__":
    unittest.main()
