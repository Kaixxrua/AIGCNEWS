from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresEvaluationRepository:
    """PostgreSQL persistence for RAG evaluation records and aggregates."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def save_evaluation(
        self,
        *,
        query: str,
        answer: str,
        sources: list[dict[str, Any]],
        recall_score: float,
        citation_score: float,
        subjective_score: float,
    ) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO rag_evaluations
                        (query, answer, sources_json, recall_score, citation_score,
                         subjective_score, evaluated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        query,
                        answer,
                        json.dumps(sources, ensure_ascii=False),
                        recall_score,
                        citation_score,
                        subjective_score,
                        _utcnow(),
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("PostgreSQL evaluation insert did not return an id")
                return int(row["id"])

    def get_eval_summary(self) -> dict[str, Any]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) AS total,
                        AVG(recall_score) AS avg_recall,
                        AVG(citation_score) AS avg_citation,
                        AVG(subjective_score) AS avg_subjective
                    FROM rag_evaluations
                    """
                )
                row = cursor.fetchone()
                return dict(row) if row else {"total": 0}

    def list_evaluations(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, query, recall_score, citation_score,
                           subjective_score, evaluated_at
                    FROM rag_evaluations
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [dict(row) for row in cursor.fetchall()]
