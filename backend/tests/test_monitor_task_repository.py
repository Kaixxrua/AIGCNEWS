from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.repositories.task_repository import (
    MonitorTaskRepository,
    RecentTaskReader,
)


class MonitorTaskRepositoryTests(unittest.TestCase):
    def test_protocol_spec_only_exposes_monitor_query(self) -> None:
        repository = MagicMock(spec=MonitorTaskRepository)

        repository.list_tasks.return_value = {"items": [], "total": 0}

        self.assertEqual(repository.list_tasks(1, 10), {"items": [], "total": 0})
        with self.assertRaises(AttributeError):
            repository.create_task("ingestion")

    def test_recent_task_reader_spec_is_read_only(self) -> None:
        repository = MagicMock(spec=RecentTaskReader)
        repository.get_recent_tasks.return_value = []

        self.assertEqual(repository.get_recent_tasks(limit=100), [])
        with self.assertRaises(AttributeError):
            repository.finish_task(42)


if __name__ == "__main__":
    unittest.main()
