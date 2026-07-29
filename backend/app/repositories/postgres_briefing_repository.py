from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresBriefingRepository:
    """PostgreSQL persistence for generated briefing content."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def save_briefing(self, date_str: str, content: str) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO briefings (date, content, created_at)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (date_str, content, _utcnow()),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("PostgreSQL briefing insert did not return an id")
                return int(row["id"])

    def get_latest_briefing(self) -> dict[str, Any] | None:
        return self._fetchone(
            """
            SELECT * FROM briefings
            ORDER BY id DESC
            LIMIT 1
            """
        )

    def get_briefing_by_date(self, date_str: str) -> dict[str, Any] | None:
        return self._fetchone(
            "SELECT * FROM briefings WHERE date = %s ORDER BY id DESC LIMIT 1",
            (date_str,),
        )

    def get_briefing(self, briefing_id: int) -> dict[str, Any] | None:
        return self._fetchone(
            "SELECT * FROM briefings WHERE id = %s",
            (briefing_id,),
        )

    def list_briefings(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, date, created_at,
                           SUBSTRING(content FROM 1 FOR 100) AS content_preview
                    FROM briefings
                    ORDER BY id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                return [dict(row) for row in cursor.fetchall()]

    def _fetchone(
        self,
        sql: str,
        params: tuple[Any, ...] = (),
    ) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return dict(row) if row else None
