from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from backend.app.core.database import DatabaseLifecycle
from backend.app.repositories.mysql_evaluation_repository import (
    MySQLEvaluationRepository,
)


class MySQLEvaluationRepositoryTests(unittest.TestCase):
    def test_save_evaluation_serializes_unicode_and_commits(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.lastrowid = 42
        sources = [{"title": "中文来源", "content": "内容"}]

        result = repository.save_evaluation(
            query="query",
            answer="answer",
            sources=sources,
            recall_score=0.5,
            citation_score=0.25,
            subjective_score=0.75,
        )

        self.assertEqual(result, 42)
        sql, params = cursor.execute.call_args.args
        self.assertIn("INSERT INTO rag_evaluations", sql)
        self.assertEqual(params[:2], ("query", "answer"))
        self.assertEqual(json.loads(params[2]), sources)
        self.assertIn("中文来源", params[2])
        self.assertEqual(params[3:6], (0.5, 0.25, 0.75))
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        connection.close.assert_called_once_with()

    def test_save_evaluation_rolls_back_and_preserves_base_exception(self) -> None:
        repository, connection, cursor = self._repository()
        error = KeyboardInterrupt("insert interrupted")
        cursor.execute.side_effect = error

        with self.assertRaises(KeyboardInterrupt) as context:
            repository.save_evaluation(
                query="query",
                answer="answer",
                sources=[],
                recall_score=0.0,
                citation_score=0.0,
                subjective_score=0.0,
            )

        self.assertIs(context.exception, error)
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_get_eval_summary_preserves_aggregate_and_read_commit(self) -> None:
        repository, connection, cursor = self._repository()
        row = {
            "total": 2,
            "avg_recall": 0.5,
            "avg_citation": 0.25,
            "avg_subjective": 0.0,
        }
        cursor.fetchone.return_value = row

        result = repository.get_eval_summary()

        self.assertEqual(result, row)
        self.assertIsNot(result, row)
        sql = cursor.execute.call_args.args[0]
        self.assertIn("COUNT(*) AS total", sql)
        self.assertIn("AVG(recall_score) AS avg_recall", sql)
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_get_eval_summary_preserves_empty_fallback(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.fetchone.return_value = None

        self.assertEqual(repository.get_eval_summary(), {"total": 0})
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_list_evaluations_preserves_projection_order_and_limit(self) -> None:
        repository, connection, cursor = self._repository()
        rows = [{"id": 2, "query": "newest"}]
        cursor.fetchall.return_value = rows

        result = repository.list_evaluations(limit=7)

        self.assertEqual(result, rows)
        self.assertIsNot(result, rows)
        sql, params = cursor.execute.call_args.args
        self.assertIn("subjective_score, evaluated_at", sql)
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
        return MySQLEvaluationRepository(database), connection, cursor


if __name__ == "__main__":
    unittest.main()
