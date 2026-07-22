from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.repositories.task_repository import IngestionTaskWriter


class IngestionTaskRepositoryTests(unittest.TestCase):
    def test_mysql_repository_exposes_ingestion_task_writer_contract(self) -> None:
        repository = MySQLRepository.__new__(MySQLRepository)

        contract: IngestionTaskWriter = repository

        self.assertTrue(callable(contract.create_task))
        self.assertTrue(callable(contract.finish_task))

    def test_protocol_spec_only_exposes_task_writes(self) -> None:
        repository = MagicMock(spec=IngestionTaskWriter)
        repository.create_task.return_value = 42

        self.assertEqual(repository.create_task("ingestion"), 42)
        repository.finish_task(42, item_count=3)

        repository.finish_task.assert_called_once_with(42, item_count=3)
        with self.assertRaises(AttributeError):
            repository.list_tasks(1, 10)


if __name__ == "__main__":
    unittest.main()
