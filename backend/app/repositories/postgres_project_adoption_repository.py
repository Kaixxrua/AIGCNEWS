from __future__ import annotations

from typing import Any

from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)
from backend.app.repositories.project_adoption_repository import (
    ProjectAdoptionRepository,
)

_COLUMNS = "id, project_full_name, decision, reason, query, source, created_at"


class PostgresProjectAdoptionRepository(ProjectAdoptionRepository):
    """PostgreSQL persistence for append-only project adoption receipts."""

    def __init__(
        self,
        database: PostgresDatabaseLifecycle = postgres_database,
    ) -> None:
        self._database = database

    def record_project_adoption(self, receipt: dict[str, Any]) -> dict[str, Any]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    INSERT INTO project_adoptions
                        (project_full_name, decision, reason, query, source)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING {_COLUMNS}
                    """,
                    (
                        receipt["project_full_name"],
                        receipt["decision"],
                        receipt.get("reason") or "",
                        receipt.get("query") or "",
                        receipt.get("source") or "mcp",
                    ),
                )
                row = cursor.fetchone()
        return dict(row)

    def get_project_adoption_stats(self, *, since_days: int = 30) -> dict[str, Any]:
        days = max(1, min(int(since_days), 365))
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT decision, COUNT(*) AS count
                    FROM project_adoptions
                    WHERE created_at >= now() - make_interval(days => %s)
                    GROUP BY decision
                    """,
                    (days,),
                )
                window_rows = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT decision, COUNT(*) AS count
                    FROM project_adoptions
                    GROUP BY decision
                    """
                )
                total_rows = cursor.fetchall()
        return {
            "window_days": days,
            "window": {row["decision"]: int(row["count"]) for row in window_rows},
            "total": {row["decision"]: int(row["count"]) for row in total_rows},
        }


def get_project_adoption_repository() -> ProjectAdoptionRepository:
    return PostgresProjectAdoptionRepository()
