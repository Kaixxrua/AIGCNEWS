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


if __name__ == "__main__":
    unittest.main()
