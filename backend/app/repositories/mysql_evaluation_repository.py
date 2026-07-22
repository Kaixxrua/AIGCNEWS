from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.app.core.database import DatabaseLifecycle


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class MySQLEvaluationRepository:
    """MySQL persistence for RAG evaluation records and aggregates."""

    def __init__(self, database: DatabaseLifecycle) -> None:
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
        sql = """
            INSERT INTO rag_evaluations
                (query, answer, sources_json, recall_score, citation_score,
                 subjective_score, evaluated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
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
                evaluation_id = cur.lastrowid
            return evaluation_id  # type: ignore[return-value]

    def get_eval_summary(self) -> dict[str, Any]:
        sql = """
            SELECT
                COUNT(*) AS total,
                AVG(recall_score) AS avg_recall,
                AVG(citation_score) AS avg_citation,
                AVG(subjective_score) AS avg_subjective
            FROM rag_evaluations
        """
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else {"total": 0}

    def list_evaluations(self, limit: int = 20) -> list[dict[str, Any]]:
        sql = """
            SELECT id, query, recall_score, citation_score, subjective_score, evaluated_at
            FROM rag_evaluations
            ORDER BY id DESC
            LIMIT %s
        """
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (limit,))
                rows = cur.fetchall()
            conn.commit()
            return list(rows)
