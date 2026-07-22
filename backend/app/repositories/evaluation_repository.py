from __future__ import annotations

from typing import Any, Protocol


class EvaluationWriter(Protocol):
    """Write boundary for persisted RAG evaluations."""

    def save_evaluation(
        self,
        *,
        query: str,
        answer: str,
        sources: list[dict[str, Any]],
        recall_score: float,
        citation_score: float,
        subjective_score: float,
    ) -> int: ...


class EvaluationSummaryReader(Protocol):
    """Read boundary for aggregate RAG evaluation metrics."""

    def get_eval_summary(self) -> dict[str, Any]: ...


class EvaluationListReader(Protocol):
    """Read boundary for recent RAG evaluation records."""

    def list_evaluations(self, limit: int = 20) -> list[dict[str, Any]]: ...


class EvaluationRepository(
    EvaluationWriter,
    EvaluationSummaryReader,
    EvaluationListReader,
    Protocol,
):
    """Combined persistence boundary used by RAG evaluation services."""
