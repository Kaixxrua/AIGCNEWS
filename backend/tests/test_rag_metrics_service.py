from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.repositories.evaluation_repository import EvaluationRepository
from backend.app.services.evaluation.rag_metrics import RAGMetricsService


class RAGMetricsServiceTests(unittest.TestCase):
    def test_evaluate_and_save_uses_injected_repository(self) -> None:
        repository = MagicMock(spec=EvaluationRepository)
        repository.save_evaluation.return_value = 42
        service = RAGMetricsService(repository)
        sources = [{"id": "source-1", "content": "answer source"}]

        result = service.evaluate_and_save(
            "query",
            "answer source-1",
            sources,
            subjective_score=0.75,
        )

        repository.save_evaluation.assert_called_once_with(
            query="query",
            answer="answer source-1",
            sources=sources,
            recall_score=0.6667,
            citation_score=1.0,
            subjective_score=0.75,
        )
        self.assertEqual(
            result,
            {
                "eval_id": 42,
                "recall_score": 0.6667,
                "citation_score": 1.0,
                "subjective_score": 0.75,
            },
        )

    def test_reads_delegate_to_injected_repository(self) -> None:
        repository = MagicMock(spec=EvaluationRepository)
        repository.get_eval_summary.return_value = {"total": 2}
        repository.list_evaluations.return_value = [{"id": 2}]
        service = RAGMetricsService(repository)

        self.assertEqual(service.get_summary(), {"total": 2})
        self.assertEqual(service.list_evaluations(limit=7), [{"id": 2}])
        repository.get_eval_summary.assert_called_once_with()
        repository.list_evaluations.assert_called_once_with(limit=7)

    def test_repository_is_required(self) -> None:
        with self.assertRaises(TypeError):
            RAGMetricsService()


if __name__ == "__main__":
    unittest.main()
