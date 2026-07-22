from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.core.database import DatabaseLifecycle


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class MySQLIngestionTaskRepository:
    """MySQL persistence for ingestion task lifecycle and history."""

    def __init__(self, database: DatabaseLifecycle) -> None:
        self._database = database

    def create_task(self, task_name: str) -> int:
        sql = """
            INSERT INTO ingestion_tasks (task_name, status, started_at)
            VALUES (%s, 'running', %s)
        """
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (task_name, _utcnow()))
                task_id = cur.lastrowid
            return task_id  # type: ignore[return-value]

    def finish_task(
        self,
        task_id: int,
        *,
        status: str = "success",
        error_msg: str | None = None,
        item_count: int = 0,
    ) -> None:
        sql = """
            UPDATE ingestion_tasks
            SET status=%s, finished_at=%s, error_msg=%s, item_count=%s
            WHERE id=%s
        """
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (status, _utcnow(), error_msg, item_count, task_id),
                )

    def get_latest_task(self) -> dict[str, Any] | None:
        sql = """
            SELECT * FROM ingestion_tasks
            ORDER BY id DESC
            LIMIT 1
        """
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
                row = cur.fetchone()
            conn.commit()
            return dict(row) if row else None

    def get_recent_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        sql = "SELECT * FROM ingestion_tasks ORDER BY id DESC LIMIT %s"
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (limit,))
                return cur.fetchall()

    def list_tasks(
        self,
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        offset = max(page - 1, 0) * page_size
        with self._database.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM ingestion_tasks")
                total_row = cur.fetchone()
                total = total_row["cnt"] if total_row else 0
                cur.execute(
                    """
                    SELECT * FROM ingestion_tasks
                    ORDER BY id DESC
                    LIMIT %s OFFSET %s
                    """,
                    (page_size, offset),
                )
                rows = cur.fetchall()
            conn.commit()
            return {
                "items": list(rows),
                "total": total,
                "page": page,
                "page_size": page_size,
            }

    def clear_all_tasks(self) -> int:
        with self._database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS cnt FROM ingestion_tasks")
                row = cur.fetchone()
                count = int(row["cnt"] if row else 0)
                cur.execute("DELETE FROM ingestion_tasks")
            return count
