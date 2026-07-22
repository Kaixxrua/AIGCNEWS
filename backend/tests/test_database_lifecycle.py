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

    def test_transaction_is_lazy_until_context_entry(self) -> None:
        connection = MagicMock()
        pool = MagicMock()
        pool.connection.return_value = connection
        pool_factory = MagicMock(return_value=pool)
        database = DatabaseLifecycle(pool_factory)

        transaction = database.transaction()

        pool_factory.assert_not_called()
        pool.connection.assert_not_called()

        with transaction as acquired:
            self.assertIs(acquired, connection)

        pool_factory.assert_called_once_with()
        pool.connection.assert_called_once_with()

    def test_transaction_commits_then_closes_on_success(self) -> None:
        events: list[str] = []
        connection = MagicMock()
        connection.commit.side_effect = lambda: events.append("commit")
        connection.close.side_effect = lambda: events.append("close")
        pool = MagicMock()
        pool.connection.return_value = connection
        database = DatabaseLifecycle(MagicMock(return_value=pool))

        with database.transaction() as acquired:
            self.assertIs(acquired, connection)

        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        connection.close.assert_called_once_with()
        self.assertEqual(events, ["commit", "close"])

    def test_transaction_rolls_back_then_closes_on_body_error(self) -> None:
        events: list[str] = []
        connection = MagicMock()
        connection.rollback.side_effect = lambda: events.append("rollback")
        connection.close.side_effect = lambda: events.append("close")
        pool = MagicMock()
        pool.connection.return_value = connection
        database = DatabaseLifecycle(MagicMock(return_value=pool))
        error = RuntimeError("sentinel")

        with self.assertRaises(RuntimeError) as context:
            with database.transaction():
                raise error

        self.assertIs(context.exception, error)
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()
        self.assertEqual(events, ["rollback", "close"])

    def test_transaction_handles_base_exception(self) -> None:
        class Sentinel(BaseException):
            pass

        connection = MagicMock()
        pool = MagicMock()
        pool.connection.return_value = connection
        database = DatabaseLifecycle(MagicMock(return_value=pool))
        error = Sentinel()

        with self.assertRaises(Sentinel) as context:
            with database.transaction():
                raise error

        self.assertIs(context.exception, error)
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_transaction_rolls_back_when_commit_fails(self) -> None:
        events: list[str] = []
        error = RuntimeError("commit failed")
        connection = MagicMock()

        def fail_commit() -> None:
            events.append("commit")
            raise error

        connection.commit.side_effect = fail_commit
        connection.rollback.side_effect = lambda: events.append("rollback")
        connection.close.side_effect = lambda: events.append("close")
        pool = MagicMock()
        pool.connection.return_value = connection
        database = DatabaseLifecycle(MagicMock(return_value=pool))

        with self.assertRaises(RuntimeError) as context:
            with database.transaction():
                pass

        self.assertIs(context.exception, error)
        connection.commit.assert_called_once_with()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()
        self.assertEqual(events, ["commit", "rollback", "close"])

    def test_transaction_preserves_body_error_when_cleanup_fails(self) -> None:
        body_error = RuntimeError("body failed")
        connection = MagicMock()
        connection.rollback.side_effect = RuntimeError("rollback failed")
        connection.close.side_effect = RuntimeError("close failed")
        pool = MagicMock()
        pool.connection.return_value = connection
        database = DatabaseLifecycle(MagicMock(return_value=pool))

        with self.assertRaises(RuntimeError) as context:
            with database.transaction():
                raise body_error

        self.assertIs(context.exception, body_error)
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_transaction_reuses_pool_across_contexts(self) -> None:
        first_connection = MagicMock()
        second_connection = MagicMock()
        pool = MagicMock()
        pool.connection.side_effect = [first_connection, second_connection]
        pool_factory = MagicMock(return_value=pool)
        database = DatabaseLifecycle(pool_factory)

        with database.transaction() as first:
            self.assertIs(first, first_connection)
        with database.transaction() as second:
            self.assertIs(second, second_connection)

        pool_factory.assert_called_once_with()
        self.assertEqual(pool.connection.call_count, 2)
        first_connection.commit.assert_called_once_with()
        first_connection.close.assert_called_once_with()
        second_connection.commit.assert_called_once_with()
        second_connection.close.assert_called_once_with()

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
