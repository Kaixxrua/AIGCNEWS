from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.core.database import DatabaseLifecycle
from backend.app.repositories.mysql_briefing_subscription_repository import (
    MySQLBriefingSubscriptionRepository,
)


class MySQLBriefingSubscriptionRepositoryTests(unittest.TestCase):
    def test_upsert_reactivates_and_returns_selected_record(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.fetchone.return_value = {
            "id": 42,
            "user_id": 7,
            "email": "reader@example.com",
            "source": "github",
            "period": "weekly",
            "is_active": 1,
        }

        result = repository.upsert_briefing_subscription(
            7,
            "reader@example.com",
            "github",
            "weekly",
        )

        self.assertEqual(result["id"], 42)
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertIn("ON DUPLICATE KEY UPDATE", cursor.execute.call_args_list[0].args[0])
        self.assertEqual(
            cursor.execute.call_args_list[0].args[1],
            (7, "reader@example.com", "github", "weekly"),
        )
        self.assertIn("WHERE user_id = %s", cursor.execute.call_args_list[1].args[0])
        self.assertEqual(cursor.execute.call_args_list[1].args[1], (7, "github", "weekly"))
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        connection.close.assert_called_once_with()

    def test_upsert_rolls_back_and_preserves_exception(self) -> None:
        repository, connection, cursor = self._repository()
        error = RuntimeError("sentinel")
        cursor.execute.side_effect = error

        with self.assertRaises(RuntimeError) as raised:
            repository.upsert_briefing_subscription(7, "reader@example.com")

        self.assertIs(raised.exception, error)
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_cancel_uses_owner_and_returns_affected_state(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.rowcount = 1

        self.assertTrue(repository.cancel_briefing_subscription(7, "news", "monthly"))

        self.assertIn("SET is_active = 0", cursor.execute.call_args.args[0])
        self.assertEqual(cursor.execute.call_args.args[1], (7, "news", "monthly"))
        connection.commit.assert_called_once_with()

    def test_cancel_rolls_back_on_failure(self) -> None:
        repository, connection, cursor = self._repository()
        error = ValueError("sentinel")
        cursor.execute.side_effect = error

        with self.assertRaises(ValueError) as raised:
            repository.cancel_briefing_subscription(7)

        self.assertIs(raised.exception, error)
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_user_reader_filters_owner_and_active_state(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.fetchall.return_value = [{"id": 42, "source": "all"}]

        result = repository.get_user_briefing_subscriptions(7)

        self.assertEqual(result, [{"id": 42, "source": "all"}])
        sql = cursor.execute.call_args.args[0]
        self.assertIn("WHERE user_id = %s AND is_active = 1", sql)
        self.assertIn("ORDER BY created_at ASC", sql)
        self.assertEqual(cursor.execute.call_args.args[1], (7,))
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_delivery_reader_filters_source_period_and_active_state(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.fetchall.return_value = [{"email": "reader@example.com"}]

        result = repository.get_active_subscribers("github", "weekly")

        self.assertEqual(result, [{"email": "reader@example.com"}])
        sql = cursor.execute.call_args.args[0]
        self.assertIn("bs.is_active = 1", sql)
        self.assertIn("bs.source = %s AND bs.period = %s", sql)
        self.assertEqual(cursor.execute.call_args.args[1], ("github", "weekly"))
        connection.commit.assert_called_once_with()
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
        return MySQLBriefingSubscriptionRepository(database), connection, cursor


if __name__ == "__main__":
    unittest.main()
