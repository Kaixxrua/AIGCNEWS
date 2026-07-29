from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.repositories.task_repository import (
    IngestionTaskAdminRepository,
    IngestionTaskWriter,
    LatestTaskReader,
)


class IngestionTaskRepositoryTests(unittest.TestCase):
    def test_protocol_spec_only_exposes_task_writes(self) -> None:
        repository = MagicMock(spec=IngestionTaskWriter)
        repository.create_task.return_value = 42

        self.assertEqual(repository.create_task("ingestion"), 42)
        repository.finish_task(42, item_count=3)

        repository.finish_task.assert_called_once_with(42, item_count=3)
        with self.assertRaises(AttributeError):
            repository.list_tasks(1, 10)

    def test_latest_task_reader_spec_is_read_only(self) -> None:
        repository = MagicMock(spec=LatestTaskReader)
        repository.get_latest_task.return_value = {"id": 42}

        self.assertEqual(repository.get_latest_task(), {"id": 42})
        with self.assertRaises(AttributeError):
            repository.finish_task(42)

    def test_task_admin_spec_only_exposes_destructive_operation(self) -> None:
        repository = MagicMock(spec=IngestionTaskAdminRepository)
        repository.clear_all_tasks.return_value = 3

        self.assertEqual(repository.clear_all_tasks(), 3)
        with self.assertRaises(AttributeError):
            repository.list_tasks(1, 10)
        with self.assertRaises(AttributeError):
            repository.create_task("ingestion")


if __name__ == "__main__":
    unittest.main()
