from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from backend.app.core.database import DatabaseLifecycle
from backend.app.repositories.mysql_user_account_repository import (
    MySQLUserAccountRepository,
)


class MySQLUserAccountRepositoryTests(unittest.TestCase):
    def test_get_user_count_preserves_read_commit_and_fallback(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.fetchone.return_value = {"cnt": 12}

        self.assertEqual(repository.get_user_count(), 12)
        self.assertEqual(cursor.execute.call_args.args, ("SELECT COUNT(*) AS cnt FROM users",))
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

        cursor.fetchone.return_value = None
        self.assertEqual(repository.get_user_count(), 0)

    def test_today_registered_count_uses_cst_date(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.fetchone.return_value = {"cnt": 2}
        fixed = datetime(2026, 7, 23, 8, 30, tzinfo=timezone(timedelta(hours=8)))

        with patch(
            "backend.app.repositories.mysql_user_account_repository.datetime"
        ) as datetime_type:
            datetime_type.now.return_value = fixed
            result = repository.get_today_registered_user_count()

        self.assertEqual(result, 2)
        sql, params = cursor.execute.call_args.args
        self.assertIn("LEFT(created_at, 10) = %s", sql)
        self.assertEqual(params, ("2026-07-23",))
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_account_reads_preserve_projection_and_normalization(self) -> None:
        repository, connection, cursor = self._repository()
        row = {"id": 42, "hashed_password": "internal-hash"}
        cursor.fetchone.return_value = row

        phone_result = repository.get_user_by_phone("13800000000")
        email_result = repository.get_user_by_email("Reader@Example.COM")

        self.assertEqual(phone_result, row)
        self.assertEqual(email_result, row)
        self.assertIsNot(phone_result, row)
        phone_call, email_call = cursor.execute.call_args_list
        self.assertIn("hashed_password", phone_call.args[0])
        self.assertEqual(phone_call.args[1], ("13800000000",))
        self.assertEqual(email_call.args[1], ("reader@example.com",))
        self.assertEqual(connection.commit.call_count, 2)
        self.assertEqual(connection.close.call_count, 2)

    def test_account_read_returns_none_for_missing_row(self) -> None:
        repository, _, cursor = self._repository()
        cursor.fetchone.return_value = None

        self.assertIsNone(repository.get_user_by_email("missing@example.com"))

    def test_create_user_preserves_defaults_and_commits(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.lastrowid = 42

        result = repository.create_user("13800000000", "reader", "hash")

        self.assertEqual(result, 42)
        sql, params = cursor.execute.call_args.args
        self.assertIn("INSERT INTO users", sql)
        self.assertEqual(params, ("13800000000", "reader", "hash", "user"))
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        connection.close.assert_called_once_with()

    def test_create_user_with_email_preserves_field_defaults(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.lastrowid = 43

        result = repository.create_user_with_email("Reader@Example.COM", "hash")

        self.assertEqual(result, 43)
        sql, params = cursor.execute.call_args.args
        self.assertIn("email_verified, invite_code_used", sql)
        self.assertIn("VALUES (%s, %s, %s, %s, 1, %s)", sql)
        self.assertEqual(params, ("reader@example.com", "", "hash", "user", ""))
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_update_password_is_scoped_to_id_and_lowercase_email(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.rowcount = 1

        result = repository.update_user_password(
            user_id=42,
            email="Reader@Example.COM",
            hashed_password="new-hash",
        )

        self.assertEqual(result, 1)
        sql, params = cursor.execute.call_args.args
        self.assertIn("WHERE id = %s AND email = %s", sql)
        self.assertEqual(params, ("new-hash", 42, "reader@example.com"))
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_each_write_rolls_back_and_preserves_base_exception(self) -> None:
        operations = (
            lambda repository: repository.create_user("phone", "name", "hash"),
            lambda repository: repository.create_user_with_email(
                "reader@example.com",
                "hash",
            ),
            lambda repository: repository.update_user_password(
                user_id=42,
                email="reader@example.com",
                hashed_password="hash",
            ),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                repository, connection, cursor = self._repository()
                error = KeyboardInterrupt("write interrupted")
                cursor.execute.side_effect = error

                with self.assertRaises(KeyboardInterrupt) as context:
                    operation(repository)

                self.assertIs(context.exception, error)
                connection.commit.assert_not_called()
                connection.rollback.assert_called_once_with()
                connection.close.assert_called_once_with()

    @staticmethod
    def _repository():
        cursor = MagicMock()
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.cursor.return_value = cursor_context
        pool = MagicMock()
        pool.connection.return_value = connection
        database = DatabaseLifecycle(MagicMock(return_value=pool))
        return MySQLUserAccountRepository(database), connection, cursor


if __name__ == "__main__":
    unittest.main()
