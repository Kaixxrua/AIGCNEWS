from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.core.database import DatabaseLifecycle, mysql_database
from backend.app.repositories.mysql_repo import MySQLRepository


class MySQLRepositoryLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_schema_initialized = MySQLRepository._schema_initialized
        MySQLRepository._schema_initialized = True

    def tearDown(self) -> None:
        MySQLRepository._schema_initialized = self.original_schema_initialized

    def test_connect_delegates_to_injected_database(self) -> None:
        connection = MagicMock()
        database = MagicMock(spec=DatabaseLifecycle)
        database.connect.return_value = connection
        repository = MySQLRepository(database=database)

        self.assertIs(repository._connect(), connection)

        database.connect.assert_called_once_with()

    def test_defaults_to_shared_database_lifecycle(self) -> None:
        first_repository = MySQLRepository()
        second_repository = MySQLRepository()

        self.assertIs(first_repository._database, mysql_database)
        self.assertIs(second_repository._database, mysql_database)

    def test_ingestion_task_component_reuses_database_lifecycle(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        repository = MySQLRepository(database=database)

        first = repository.ingestion_tasks
        second = repository.ingestion_tasks

        self.assertIs(first, second)
        self.assertIs(first._database, database)

    def test_ingestion_task_component_does_not_create_pool(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        repository = MySQLRepository(database=database)

        _ = repository.ingestion_tasks

        database.connect.assert_not_called()

    def test_briefing_component_reuses_database_lifecycle(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        repository = MySQLRepository(database=database)

        first = repository.briefings
        second = repository.briefings

        self.assertIs(first, second)
        self.assertIs(first._database, database)
        self.assertIsNot(first, repository.ingestion_tasks)
        database.connect.assert_not_called()

    def test_preserves_single_schema_initialization(self) -> None:
        MySQLRepository._schema_initialized = False
        database = MagicMock(spec=DatabaseLifecycle)

        with patch.object(MySQLRepository, "_init_schema") as initialize_schema:
            MySQLRepository(database=database)
            MySQLRepository(database=database)

        initialize_schema.assert_called_once_with()
        self.assertTrue(MySQLRepository._schema_initialized)

    def test_repository_connection_close_returns_through_shared_pool(self) -> None:
        connection = MagicMock()
        pool = MagicMock()
        pool.connection.return_value = connection
        database = DatabaseLifecycle(MagicMock(return_value=pool))
        repository = MySQLRepository(database=database)

        acquired = repository._connect()
        acquired.close()

        self.assertIs(acquired, connection)
        pool.connection.assert_called_once_with()
        connection.close.assert_called_once_with()
        pool.close.assert_not_called()

    def test_task_compatibility_methods_delegate_to_component(self) -> None:
        repository = MySQLRepository(database=MagicMock(spec=DatabaseLifecycle))
        task_repository = MagicMock()
        task_repository.create_task.return_value = 42
        task_repository.get_latest_task.return_value = {"id": 42}
        task_repository.get_recent_tasks.return_value = [{"id": 42}]
        task_repository.list_tasks.return_value = {"items": [{"id": 42}]}
        task_repository.clear_all_tasks.return_value = 1
        repository._ingestion_tasks = task_repository

        self.assertEqual(repository.create_task("multi_source_ingest"), 42)
        repository.finish_task(
            42,
            status="failed",
            error_msg="sentinel",
            item_count=3,
        )
        self.assertEqual(repository.get_latest_task(), {"id": 42})
        self.assertEqual(repository.get_recent_tasks(limit=7), [{"id": 42}])
        self.assertEqual(repository.list_tasks(page=2, page_size=3), {"items": [{"id": 42}]})
        self.assertEqual(repository.clear_all_tasks(), 1)

        task_repository.create_task.assert_called_once_with("multi_source_ingest")
        task_repository.finish_task.assert_called_once_with(
            42,
            status="failed",
            error_msg="sentinel",
            item_count=3,
        )
        task_repository.get_latest_task.assert_called_once_with()
        task_repository.get_recent_tasks.assert_called_once_with(7)
        task_repository.list_tasks.assert_called_once_with(2, 3)
        task_repository.clear_all_tasks.assert_called_once_with()

    @staticmethod
    def _repository_with_database():
        cursor = MagicMock()
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.cursor.return_value = cursor_context
        pool = MagicMock()
        pool.connection.return_value = connection
        database = DatabaseLifecycle(MagicMock(return_value=pool))
        repository = MySQLRepository(database=database)
        return repository, connection, cursor


if __name__ == "__main__":
    unittest.main()
