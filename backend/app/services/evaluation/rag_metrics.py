from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from backend.app.repositories.application_repository_context import (
    get_configured_application_repositories,
)
from backend.app.repositories.evaluation_repository import EvaluationRepository


def _jaccard_similarity(set_a: set, set_b: set) -> float:
    """Compute Jaccard similarity between two token sets."""
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def _tokenize(text: str) -> set:
    """Simple whitespace + punctuation tokenizer (language-agnostic)."""
    tokens = re.findall(r"\w+", text.lower())
    return set(tokens)


class RAGMetricsService:
    """
    Compute and persist RAG evaluation metrics.

    Metrics:
      - recall_score:     token-level Jaccard overlap between answer and source chunks
      - citation_score:   fraction of answer sentences that contain a citation marker
      - subjective_score: (placeholder) always 0 unless explicitly provided
    """

    def __init__(self, repository: Optional[EvaluationRepository] = None) -> None:
        self._repository = (
            repository
            or get_configured_application_repositories().evaluations
        )

    # ------------------------------------------------------------------
    # Core metric functions
    # ------------------------------------------------------------------

    @staticmethod
    def compute_recall(answer: str, sources: List[Dict[str, Any]]) -> float:
        """
        Estimate how much of the answer can be traced back to the source chunks.
        Uses macro-average Jaccard similarity across all source texts.
        """
        if not answer or not sources:
            return 0.0

        answer_tokens = _tokenize(answer)
        scores: List[float] = []
        for src in sources:
            content = src.get("content") or src.get("page_content") or ""
            if content:
                scores.append(_jaccard_similarity(answer_tokens, _tokenize(content)))

        return round(sum(scores) / len(scores), 4) if scores else 0.0

    @staticmethod
    def compute_citation_coverage(answer: str, sources: List[Dict[str, Any]]) -> float:
        """
        Fraction of source documents whose ID is referenced in the answer text.
        A simple heuristic: check if doc id/title keywords appear in the answer.
        """
        if not sources:
            return 0.0

        answer_lower = answer.lower()
        cited = 0
        for src in sources:
            src_id = str(src.get("id") or src.get("source_id") or "")
            title = str(src.get("title") or "")
            url = str(src.get("url") or "")
            # Consider "cited" if any identifier token appears in the answer
            identifiers = [src_id, title[:30], url]
            if any(
                ident.lower() and ident.lower() in answer_lower
                for ident in identifiers
                if ident.strip()
            ):
                cited += 1

        return round(cited / len(sources), 4)

    # ------------------------------------------------------------------
    # Evaluate and persist
    # ------------------------------------------------------------------

    def evaluate_and_save(
        self,
        query: str,
        answer: str,
        sources: List[Dict[str, Any]],
        subjective_score: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Compute all metrics, persist them, and return the result dict.
        """
        recall = self.compute_recall(answer, sources)
        citation = self.compute_citation_coverage(answer, sources)

        eval_id = self._repository.save_evaluation(
            query=query,
            answer=answer,
            sources=sources,
            recall_score=recall,
            citation_score=citation,
            subjective_score=subjective_score,
        )
        return {
            "eval_id": eval_id,
            "recall_score": recall,
            "citation_score": citation,
            "subjective_score": subjective_score,
        }

    def get_summary(self) -> Dict[str, Any]:
        """Return aggregated evaluation statistics."""
        return self._repository.get_eval_summary()

    def list_evaluations(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._repository.list_evaluations(limit=limit)
