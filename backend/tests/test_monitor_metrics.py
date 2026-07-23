from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.monitoring.metrics import _task_summary, collect_metrics
from backend.app.repositories.evaluation_repository import EvaluationSummaryReader
from backend.app.repositories.task_repository import (
    MonitorMetricsRepository,
    RecentTaskReader,
)


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

    def test_collect_metrics_uses_injected_repository_for_all_reads(self) -> None:
        repository = MagicMock(spec=MonitorMetricsRepository)
        task_reader = MagicMock(spec=RecentTaskReader)
        evaluation_reader = MagicMock(spec=EvaluationSummaryReader)
        task_reader.get_recent_tasks.return_value = []
        evaluation_reader.get_eval_summary.return_value = {"score": 0.9}
        repository.get_document_count.return_value = 12
        repository.list_briefings.return_value = [{"id": 1}, {"id": 2}]

        with patch(
            "backend.app.monitoring.metrics.MySQLRepository"
        ) as repository_type:
            result = collect_metrics(repository, task_reader, evaluation_reader)

        repository_type.assert_not_called()
        task_reader.get_recent_tasks.assert_called_once_with(limit=100)
        evaluation_reader.get_eval_summary.assert_called_once_with()
        repository.get_document_count.assert_called_once_with()
        repository.list_briefings.assert_called_once_with(limit=1000)
        self.assertEqual(result["document_count"], 12)
        self.assertEqual(result["briefing_count"], 2)
        self.assertEqual(result["rag_evaluation"], {"score": 0.9})

    def test_collect_metrics_uses_default_repository_task_component(self) -> None:
        repository = MagicMock(spec=MonitorMetricsRepository)
        task_reader = MagicMock(spec=RecentTaskReader)
        evaluation_reader = MagicMock(spec=EvaluationSummaryReader)
        task_reader.get_recent_tasks.return_value = []
        evaluation_reader.get_eval_summary.return_value = {}
        repository.ingestion_tasks = task_reader
        repository.evaluations = evaluation_reader
        repository.get_document_count.return_value = 0
        repository.list_briefings.return_value = []

        with patch(
            "backend.app.monitoring.metrics.MySQLRepository",
            return_value=repository,
        ):
            collect_metrics()

        task_reader.get_recent_tasks.assert_called_once_with(limit=100)
        evaluation_reader.get_eval_summary.assert_called_once_with()

    def test_collect_metrics_preserves_independent_error_fallbacks(self) -> None:
        repository = MagicMock(spec=MonitorMetricsRepository)
        task_reader = MagicMock(spec=RecentTaskReader)
        evaluation_reader = MagicMock(spec=EvaluationSummaryReader)
        task_reader.get_recent_tasks.side_effect = RuntimeError("tasks")
        evaluation_reader.get_eval_summary.side_effect = RuntimeError("eval")
        repository.get_document_count.side_effect = RuntimeError("documents")
        repository.list_briefings.side_effect = RuntimeError("briefings")

        result = collect_metrics(repository, task_reader, evaluation_reader)

        self.assertEqual(result["tasks"], {"error": "tasks"})
        self.assertEqual(result["rag_evaluation"], {"error": "eval"})
        self.assertEqual(result["document_count"], -1)
        self.assertEqual(result["briefing_count"], -1)


if __name__ == "__main__":
    unittest.main()
