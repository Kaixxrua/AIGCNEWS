from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.repositories.evaluation_repository import (
    EvaluationListReader,
    EvaluationSummaryReader,
    EvaluationWriter,
)


class EvaluationRepositoryContractTests(unittest.TestCase):
    def test_writer_spec_does_not_expose_reads(self) -> None:
        repository = MagicMock(spec=EvaluationWriter)
        repository.save_evaluation.return_value = 42

        self.assertEqual(
            repository.save_evaluation(
                query="query",
                answer="answer",
                sources=[{"title": "source"}],
                recall_score=0.5,
                citation_score=0.25,
                subjective_score=0.0,
            ),
            42,
        )
        with self.assertRaises(AttributeError):
            repository.get_eval_summary()

    def test_summary_reader_spec_does_not_expose_records_or_writes(self) -> None:
        repository = MagicMock(spec=EvaluationSummaryReader)
        repository.get_eval_summary.return_value = {"total": 1}

        self.assertEqual(repository.get_eval_summary(), {"total": 1})
        with self.assertRaises(AttributeError):
            repository.list_evaluations()
        with self.assertRaises(AttributeError):
            repository.save_evaluation()

    def test_list_reader_preserves_default_limit_capability(self) -> None:
        repository = MagicMock(spec=EvaluationListReader)
        repository.list_evaluations.return_value = [{"id": 42}]

        self.assertEqual(repository.list_evaluations(), [{"id": 42}])
        repository.list_evaluations.assert_called_once_with()
        with self.assertRaises(AttributeError):
            repository.get_eval_summary()


if __name__ == "__main__":
    unittest.main()
