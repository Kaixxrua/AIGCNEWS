from __future__ import annotations

from datetime import datetime
from typing import Any, Sequence

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.error_event_repository import ErrorEventInsert


class PostgresErrorEventRepository:
    """PostgreSQL persistence for backend error events."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def insert_events(self, events: Sequence[ErrorEventInsert]) -> int:
        if not events:
            return 0
        rows = [
            (
                event.occurred_at,
                event.level,
                event.logger_name,
                event.message,
                event.exception_type,
                event.stack_trace,
            )
            for event in events
        ]
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO error_events
                        (occurred_at, level, logger_name, message,
                         exception_type, stack_trace)
                    VALUES (COALESCE(%s, CURRENT_TIMESTAMP), %s, %s, %s, %s, %s)
                    """,
                    rows,
                )
                return cursor.rowcount

    def list_events(self, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        offset = max(page - 1, 0) * page_size
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS cnt FROM error_events")
                total_row = cursor.fetchone()
                total = int(total_row["cnt"] if total_row else 0)
                cursor.execute(
                    "SELECT * FROM error_events ORDER BY id DESC LIMIT %s OFFSET %s",
                    (page_size, offset),
                )
                rows = cursor.fetchall()
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    def prune_older_than(self, cutoff: datetime) -> int:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM error_events WHERE occurred_at < %s",
                    (cutoff,),
                )
                return cursor.rowcount
