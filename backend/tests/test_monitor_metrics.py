from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.monitoring.metrics import _task_summary
from backend.app.repositories.task_repository import RecentTaskReader


class MonitorMetricsTests(unittest.TestCase):
    def test_task_summary_counts_statuses_and_preserves_last_task(self) -> None:
        repository = MagicMock(spec=RecentTaskReader)
        latest = {"id": 4, "status": "running", "detail": "unchanged"}
        repository.get_recent_tasks.return_value = [
            latest,
            {"id": 3, "status": "success"},
            {"id": 2, "status": "success"},
            {"id": 1, "status": "failed"},
        ]

        result = _task_summary(repository)

        self.assertEqual(
            result,
            {
                "total": 4,
                "success": 2,
                "failed": 1,
                "running": 1,
                "last_task": latest,
            },
        )
        self.assertIs(result["last_task"], latest)
        repository.get_recent_tasks.assert_called_once_with(limit=100)

    def test_task_summary_handles_empty_task_list(self) -> None:
        repository = MagicMock(spec=RecentTaskReader)
        repository.get_recent_tasks.return_value = []

        self.assertEqual(
            _task_summary(repository),
            {
                "total": 0,
                "success": 0,
                "failed": 0,
                "running": 0,
                "last_task": None,
            },
        )


if __name__ == "__main__":
    unittest.main()
