from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import pymysql

from backend.app.core.database import DatabaseLifecycle, create_mysql_pool


class DatabaseLifecycleTests(unittest.TestCase):
    def test_does_not_create_pool_until_first_connect(self) -> None:
        pool = MagicMock()
        pool_factory = MagicMock(return_value=pool)
        database = DatabaseLifecycle(pool_factory)

        pool_factory.assert_not_called()

        database.connect()

        pool_factory.assert_called_once_with()

    def test_connect_reuses_one_pool(self) -> None:
        first_connection = MagicMock()
        second_connection = MagicMock()
        pool = MagicMock()
        pool.connection.side_effect = [first_connection, second_connection]
        pool_factory = MagicMock(return_value=pool)
        database = DatabaseLifecycle(pool_factory)

        self.assertIs(database.connect(), first_connection)
        self.assertIs(database.connect(), second_connection)

        pool_factory.assert_called_once_with()
        self.assertEqual(pool.connection.call_count, 2)

    def test_connection_context_closes_connection_on_success(self) -> None:
        connection = MagicMock()
        pool = MagicMock()
        pool.connection.return_value = connection
        database = DatabaseLifecycle(MagicMock(return_value=pool))

        with database.connection() as acquired:
            self.assertIs(acquired, connection)

        connection.close.assert_called_once_with()
        connection.commit.assert_not_called()
        connection.rollback.assert_not_called()

    def test_connection_context_closes_connection_on_error(self) -> None:
        connection = MagicMock()
        pool = MagicMock()
        pool.connection.return_value = connection
        database = DatabaseLifecycle(MagicMock(return_value=pool))

        with self.assertRaisesRegex(RuntimeError, "sentinel"):
            with database.connection():
                raise RuntimeError("sentinel")

        connection.close.assert_called_once_with()
        connection.commit.assert_not_called()
        connection.rollback.assert_not_called()

    def test_close_before_first_connect_does_not_create_pool(self) -> None:
        pool_factory = MagicMock()
        database = DatabaseLifecycle(pool_factory)

        database.close()

        pool_factory.assert_not_called()

    def test_close_closes_initialized_pool(self) -> None:
        pool = MagicMock()
        database = DatabaseLifecycle(MagicMock(return_value=pool))
        database.connect()

        database.close()

        pool.close.assert_called_once_with()

    def test_connect_after_close_creates_new_pool(self) -> None:
        first_connection = MagicMock()
        second_connection = MagicMock()
        first_pool = MagicMock()
        second_pool = MagicMock()
        first_pool.connection.return_value = first_connection
        second_pool.connection.return_value = second_connection
        pool_factory = MagicMock(side_effect=[first_pool, second_pool])
        database = DatabaseLifecycle(pool_factory)

        self.assertIs(database.connect(), first_connection)
        database.close()
        self.assertIs(database.connect(), second_connection)

        self.assertEqual(pool_factory.call_count, 2)
        first_pool.close.assert_called_once_with()
        second_pool.close.assert_not_called()


class CreateMySQLPoolTests(unittest.TestCase):
    def test_preserves_repository_configuration(self) -> None:
        config = SimpleNamespace(
            mysql_host="db.internal",
            mysql_port=4406,
            mysql_user="aigc",
            mysql_password="secret",
            mysql_database="aigc_test",
        )
        pool = MagicMock()
        pool_constructor = MagicMock(return_value=pool)

        result = create_mysql_pool(
            config=config,
            pool_constructor=pool_constructor,
        )

        self.assertIs(result, pool)
        pool_constructor.assert_called_once_with(
            creator=pymysql,
            mincached=2,
            maxcached=5,
            maxconnections=20,
            blocking=True,
            host="db.internal",
            port=4406,
            user="aigc",
            password="secret",
            database="aigc_test",
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
            setsession=["SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci"],
        )

    def test_supports_existing_configuration_defaults(self) -> None:
        pool_constructor = MagicMock(return_value=MagicMock())

        create_mysql_pool(
            config=SimpleNamespace(),
            pool_constructor=pool_constructor,
        )

        kwargs = pool_constructor.call_args.kwargs
        self.assertEqual(kwargs["host"], "localhost")
        self.assertEqual(kwargs["port"], 3306)
        self.assertEqual(kwargs["user"], "root")
        self.assertEqual(kwargs["password"], "")
        self.assertEqual(kwargs["database"], "rag_aigc")


if __name__ == "__main__":
    unittest.main()
