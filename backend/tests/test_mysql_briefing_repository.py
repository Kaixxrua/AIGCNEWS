from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.core.database import DatabaseLifecycle
from backend.app.repositories.mysql_briefing_repository import MySQLBriefingRepository


class MySQLBriefingRepositoryTests(unittest.TestCase):
    def test_save_briefing_commits_and_returns_id(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.lastrowid = 42

        result = repository.save_briefing("2026-07-22", "content")

        self.assertEqual(result, 42)
        sql, params = cursor.execute.call_args.args
        self.assertIn("INSERT INTO briefings", sql)
        self.assertEqual(params[:2], ("2026-07-22", "content"))
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        connection.close.assert_called_once_with()

    def test_save_briefing_rolls_back_and_preserves_error(self) -> None:
        repository, connection, cursor = self._repository()
        error = RuntimeError("insert failed")
        cursor.execute.side_effect = error

        with self.assertRaises(RuntimeError) as context:
            repository.save_briefing("2026-07-22", "content")

        self.assertIs(context.exception, error)
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_get_latest_briefing_preserves_order_and_read_commit(self) -> None:
        repository, connection, cursor = self._repository()
        row = {"id": 42, "content": "content"}
        cursor.fetchone.return_value = row

        result = repository.get_latest_briefing()

        self.assertEqual(result, row)
        self.assertIsNot(result, row)
        sql = cursor.execute.call_args.args[0]
        self.assertIn("ORDER BY id DESC", sql)
        self.assertIn("LIMIT 1", sql)
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_get_latest_briefing_returns_none_when_empty(self) -> None:
        repository, _, cursor = self._repository()
        cursor.fetchone.return_value = None

        self.assertIsNone(repository.get_latest_briefing())

    def test_get_briefing_by_date_preserves_query_and_row_shape(self) -> None:
        repository, connection, cursor = self._repository()
        row = {"id": 42, "date": "2026-07-22"}
        cursor.fetchone.return_value = row

        result = repository.get_briefing_by_date("2026-07-22")

        self.assertEqual(result, row)
        cursor.execute.assert_called_once_with(
            "SELECT * FROM briefings WHERE date = %s ORDER BY id DESC LIMIT 1",
            ("2026-07-22",),
        )
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_get_briefing_by_date_returns_none_when_missing(self) -> None:
        repository, _, cursor = self._repository()
        cursor.fetchone.return_value = None

        self.assertIsNone(repository.get_briefing_by_date("2026-07-22"))

    def test_list_briefings_preserves_preview_order_and_limit(self) -> None:
        repository, connection, cursor = self._repository()
        rows = [{"id": 2, "content_preview": "two"}]
        cursor.fetchall.return_value = rows

        result = repository.list_briefings(limit=7)

        self.assertEqual(result, rows)
        self.assertIsNot(result, rows)
        sql, params = cursor.execute.call_args.args
        self.assertIn("SUBSTRING(content, 1, 100) AS content_preview", sql)
        self.assertIn("ORDER BY id DESC", sql)
        self.assertEqual(params, (7,))
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
        return MySQLBriefingRepository(database), connection, cursor


if __name__ == "__main__":
    unittest.main()
