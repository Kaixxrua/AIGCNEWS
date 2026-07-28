from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class PostgresIngestionTaskRepository:
    """PostgreSQL persistence for ingestion task lifecycle and history."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def create_task(self, task_name: str) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO ingestion_tasks (task_name, status, started_at)
                    VALUES (%s, 'running', %s)
                    RETURNING id
                    """,
                    (task_name, _utcnow()),
                )
                row = cursor.fetchone()
                if row is None:
                    raise RuntimeError("PostgreSQL ingestion task insert did not return an id")
                return int(row["id"])

    def finish_task(
        self,
        task_id: int,
        *,
        status: str = "success",
        error_msg: str | None = None,
        item_count: int = 0,
    ) -> None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE ingestion_tasks
                    SET status=%s, finished_at=%s, error_msg=%s, item_count=%s
                    WHERE id=%s
                    """,
                    (status, _utcnow(), error_msg, item_count, task_id),
                )

    def get_latest_task(self) -> dict[str, Any] | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM ingestion_tasks ORDER BY id DESC LIMIT 1")
                row = cursor.fetchone()
                return dict(row) if row else None

    def get_recent_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM ingestion_tasks ORDER BY id DESC LIMIT %s",
                    (limit,),
                )
                return [dict(row) for row in cursor.fetchall()]

    def list_tasks(self, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        offset = max(page - 1, 0) * page_size
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS cnt FROM ingestion_tasks")
                total_row = cursor.fetchone()
                total = int(total_row["cnt"] if total_row else 0)
                cursor.execute(
                    "SELECT * FROM ingestion_tasks ORDER BY id DESC LIMIT %s OFFSET %s",
                    (page_size, offset),
                )
                rows = cursor.fetchall()
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def clear_all_tasks(self) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS cnt FROM ingestion_tasks")
                row = cursor.fetchone()
                count = int(row["cnt"] if row else 0)
                cursor.execute("DELETE FROM ingestion_tasks")
                return count
