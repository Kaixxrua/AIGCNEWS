from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.monitoring.metrics import _task_summary, collect_metrics
from backend.app.repositories.briefing_repository import BriefingReader
from backend.app.repositories.document_repository import DocumentStatisticsReader
from backend.app.repositories.evaluation_repository import EvaluationSummaryReader
from backend.app.repositories.task_repository import RecentTaskReader


class MonitorMetricsTests(unittest.TestCase):
    def test_task_summary_counts_statuses_and_preserves_last_task(self) -> None:
        repository = MagicMock(spec=RecentTaskReader)
        latest = {"id": 4, "status": "running", "detail": "unchanged"}
        repository.get_recent_tasks.return_value = [
            latest,
            {"id": 3, "status": "success"},
            {"id": 2, "status": "success"},
            {"id": 1, "status": "failed"},
        ]

        result = _task_summary(repository)

        self.assertEqual(
            result,
            {
                "total": 4,
                "success": 2,
                "failed": 1,
                "running": 1,
                "last_task": latest,
            },
        )
        self.assertIs(result["last_task"], latest)
        repository.get_recent_tasks.assert_called_once_with(limit=100)

    def test_task_summary_handles_empty_task_list(self) -> None:
        repository = MagicMock(spec=RecentTaskReader)
        repository.get_recent_tasks.return_value = []

        self.assertEqual(
            _task_summary(repository),
            {
                "total": 0,
                "success": 0,
                "failed": 0,
                "running": 0,
                "last_task": None,
            },
        )

    def test_collect_metrics_uses_injected_readers(self) -> None:
        task_reader = MagicMock(spec=RecentTaskReader)
        evaluation_reader = MagicMock(spec=EvaluationSummaryReader)
        document_statistics = MagicMock(spec=DocumentStatisticsReader)
        briefing_reader = MagicMock(spec=BriefingReader)
        task_reader.get_recent_tasks.return_value = []
        evaluation_reader.get_eval_summary.return_value = {"score": 0.9}
        document_statistics.get_document_count.return_value = 12
        briefing_reader.list_briefings.return_value = [{"id": 1}, {"id": 2}]

        result = collect_metrics(
            task_reader=task_reader,
            evaluation_reader=evaluation_reader,
            document_statistics=document_statistics,
            briefing_reader=briefing_reader,
        )

        task_reader.get_recent_tasks.assert_called_once_with(limit=100)
        evaluation_reader.get_eval_summary.assert_called_once_with()
        document_statistics.get_document_count.assert_called_once_with()
        briefing_reader.list_briefings.assert_called_once_with(limit=1000)
        self.assertEqual(result["document_count"], 12)
        self.assertEqual(result["briefing_count"], 2)
        self.assertEqual(result["rag_evaluation"], {"score": 0.9})

    def test_collect_metrics_preserves_independent_error_fallbacks(self) -> None:
        task_reader = MagicMock(spec=RecentTaskReader)
        evaluation_reader = MagicMock(spec=EvaluationSummaryReader)
        document_statistics = MagicMock(spec=DocumentStatisticsReader)
        briefing_reader = MagicMock(spec=BriefingReader)
        task_reader.get_recent_tasks.side_effect = RuntimeError("tasks")
        evaluation_reader.get_eval_summary.side_effect = RuntimeError("eval")
        document_statistics.get_document_count.side_effect = RuntimeError("documents")
        briefing_reader.list_briefings.side_effect = RuntimeError("briefings")

        result = collect_metrics(
            task_reader=task_reader,
            evaluation_reader=evaluation_reader,
            document_statistics=document_statistics,
            briefing_reader=briefing_reader,
        )

        self.assertEqual(result["tasks"], {"error": "tasks"})
        self.assertEqual(result["rag_evaluation"], {"error": "eval"})
        self.assertEqual(result["document_count"], -1)
        self.assertEqual(result["briefing_count"], -1)


if __name__ == "__main__":
    unittest.main()
