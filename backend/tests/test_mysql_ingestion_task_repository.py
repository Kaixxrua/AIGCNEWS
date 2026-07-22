from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.core.database import DatabaseLifecycle
from backend.app.repositories.mysql_ingestion_task_repository import (
    MySQLIngestionTaskRepository,
)


class MySQLIngestionTaskRepositoryTests(unittest.TestCase):
    def test_create_task_commits_and_returns_task_id(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.lastrowid = 42

        task_id = repository.create_task("multi_source_ingest")

        self.assertEqual(task_id, 42)
        sql, params = cursor.execute.call_args.args
        self.assertIn("INSERT INTO ingestion_tasks", sql)
        self.assertEqual(params[0], "multi_source_ingest")
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        connection.close.assert_called_once_with()

    def test_create_task_rolls_back_and_preserves_error(self) -> None:
        repository, connection, cursor = self._repository()
        error = RuntimeError("insert failed")
        cursor.execute.side_effect = error

        with self.assertRaises(RuntimeError) as context:
            repository.create_task("multi_source_ingest")

        self.assertIs(context.exception, error)
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_finish_task_preserves_parameters(self) -> None:
        repository, connection, cursor = self._repository()

        repository.finish_task(
            42,
            status="failed",
            error_msg="sentinel",
            item_count=3,
        )

        sql, params = cursor.execute.call_args.args
        self.assertIn("UPDATE ingestion_tasks", sql)
        self.assertEqual(params[0], "failed")
        self.assertEqual(params[2:], ("sentinel", 3, 42))
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        connection.close.assert_called_once_with()

    def test_finish_task_rolls_back_and_preserves_error(self) -> None:
        repository, connection, cursor = self._repository()
        error = RuntimeError("update failed")
        cursor.execute.side_effect = error

        with self.assertRaises(RuntimeError) as context:
            repository.finish_task(42)

        self.assertIs(context.exception, error)
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_get_latest_task_preserves_read_commit_and_row_shape(self) -> None:
        repository, connection, cursor = self._repository()
        row = {"id": 42, "status": "success"}
        cursor.fetchone.return_value = row

        result = repository.get_latest_task()

        self.assertEqual(result, row)
        self.assertIsNot(result, row)
        self.assertIn("ORDER BY id DESC", cursor.execute.call_args.args[0])
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_get_latest_task_returns_none_for_empty_table(self) -> None:
        repository, _, cursor = self._repository()
        cursor.fetchone.return_value = None

        self.assertIsNone(repository.get_latest_task())

    def test_get_recent_tasks_preserves_limit_and_rows(self) -> None:
        repository, connection, cursor = self._repository()
        rows = [{"id": 2}, {"id": 1}]
        cursor.fetchall.return_value = rows

        result = repository.get_recent_tasks(limit=7)

        self.assertIs(result, rows)
        cursor.execute.assert_called_once_with(
            "SELECT * FROM ingestion_tasks ORDER BY id DESC LIMIT %s",
            (7,),
        )
        connection.commit.assert_not_called()
        connection.close.assert_called_once_with()

    def test_list_tasks_preserves_pagination_and_result_shape(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.fetchone.return_value = {"cnt": 3}
        cursor.fetchall.return_value = [{"id": 2}, {"id": 1}]

        result = repository.list_tasks(page=2, page_size=2)

        self.assertEqual(
            result,
            {
                "items": [{"id": 2}, {"id": 1}],
                "total": 3,
                "page": 2,
                "page_size": 2,
            },
        )
        self.assertEqual(cursor.execute.call_count, 2)
        _, params = cursor.execute.call_args.args
        self.assertEqual(params, (2, 2))
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_clear_all_tasks_commits_and_returns_previous_count(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.fetchone.return_value = {"cnt": 3}

        result = repository.clear_all_tasks()

        self.assertEqual(result, 3)
        self.assertEqual(cursor.execute.call_count, 2)
        self.assertEqual(cursor.execute.call_args.args[0], "DELETE FROM ingestion_tasks")
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        connection.close.assert_called_once_with()

    def test_clear_all_tasks_rolls_back_and_preserves_delete_error(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.fetchone.return_value = {"cnt": 3}
        error = RuntimeError("delete failed")
        cursor.execute.side_effect = [None, error]

        with self.assertRaises(RuntimeError) as context:
            repository.clear_all_tasks()

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
        return MySQLIngestionTaskRepository(database), connection, cursor


if __name__ == "__main__":
    unittest.main()
