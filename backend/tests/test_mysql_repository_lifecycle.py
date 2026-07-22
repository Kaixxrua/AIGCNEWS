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

    def test_create_task_uses_transaction_and_returns_task_id(self) -> None:
        repository, connection, cursor = self._repository_with_database()
        cursor.lastrowid = 42

        task_id = repository.create_task("multi_source_ingest")

        self.assertEqual(task_id, 42)
        cursor.execute.assert_called_once()
        sql, params = cursor.execute.call_args.args
        self.assertIn("INSERT INTO ingestion_tasks", sql)
        self.assertEqual(params[0], "multi_source_ingest")
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        connection.close.assert_called_once_with()

    def test_create_task_rolls_back_and_preserves_sql_error(self) -> None:
        repository, connection, cursor = self._repository_with_database()
        error = RuntimeError("insert failed")
        cursor.execute.side_effect = error

        with self.assertRaises(RuntimeError) as context:
            repository.create_task("multi_source_ingest")

        self.assertIs(context.exception, error)
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_create_task_rolls_back_and_preserves_commit_error(self) -> None:
        repository, connection, cursor = self._repository_with_database()
        cursor.lastrowid = 42
        error = RuntimeError("commit failed")
        connection.commit.side_effect = error

        with self.assertRaises(RuntimeError) as context:
            repository.create_task("multi_source_ingest")

        self.assertIs(context.exception, error)
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_finish_task_uses_transaction(self) -> None:
        repository, connection, cursor = self._repository_with_database()

        repository.finish_task(
            42,
            status="failed",
            error_msg="sentinel",
            item_count=3,
        )

        cursor.execute.assert_called_once()
        sql, params = cursor.execute.call_args.args
        self.assertIn("UPDATE ingestion_tasks", sql)
        self.assertEqual(params[0], "failed")
        self.assertEqual(params[2:], ("sentinel", 3, 42))
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        connection.close.assert_called_once_with()

    def test_finish_task_rolls_back_and_preserves_sql_error(self) -> None:
        repository, connection, cursor = self._repository_with_database()
        error = RuntimeError("update failed")
        cursor.execute.side_effect = error

        with self.assertRaises(RuntimeError) as context:
            repository.finish_task(42)

        self.assertIs(context.exception, error)
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()

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
