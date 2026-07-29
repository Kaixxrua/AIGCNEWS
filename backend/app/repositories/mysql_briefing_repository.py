from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.core.database import DatabaseLifecycle


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class MySQLBriefingRepository:
    """MySQL persistence for generated briefing content."""

    def __init__(self, database: DatabaseLifecycle) -> None:
        self._database = database

    def save_briefing(self, date_str: str, content: str) -> int:
        sql = """
            INSERT INTO briefings (date, content, created_at)
            VALUES (%s, %s, %s)
        """
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (date_str, content, _utcnow()))
                briefing_id = cur.lastrowid
            return briefing_id  # type: ignore[return-value]

    def get_latest_briefing(self) -> dict[str, Any] | None:
        sql = """
            SELECT * FROM briefings
            ORDER BY id DESC
            LIMIT 1
        """
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None

    def get_briefing_by_date(self, date_str: str) -> dict[str, Any] | None:
        sql = "SELECT * FROM briefings WHERE date = %s ORDER BY id DESC LIMIT 1"
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (date_str,))
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None

    def get_briefing(self, briefing_id: int) -> dict[str, Any] | None:
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM briefings WHERE id = %s", (briefing_id,))
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None

    def list_briefings(self, limit: int = 30) -> list[dict[str, Any]]:
        sql = """
            SELECT id, date, created_at,
                   SUBSTRING(content, 1, 100) AS content_preview
            FROM briefings
            ORDER BY id DESC
            LIMIT %s
        """
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (limit,))
                rows = cur.fetchall()
            conn.commit()
            return list(rows)
