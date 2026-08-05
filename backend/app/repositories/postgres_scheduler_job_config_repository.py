from __future__ import annotations

from datetime import time
from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.scheduler_job_config_repository import (
    SchedulerJobConfig,
)


class PostgresSchedulerJobConfigRepository:
    """PostgreSQL persistence for per-job scheduler windows."""

    def __init__(self, database: PostgresDatabaseLifecycle) -> None:
        self._database = database

    def list_scheduler_job_configs(self) -> list[SchedulerJobConfig]:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT job_id, start_time, end_time, interval_minutes, enabled
                    FROM scheduler_job_config
                    ORDER BY job_id
                    """
                )
                return [self._row_to_config(row) for row in cursor.fetchall()]

    def get_scheduler_job_config(self, job_id: str) -> SchedulerJobConfig | None:
        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT job_id, start_time, end_time, interval_minutes, enabled
                    FROM scheduler_job_config
                    WHERE job_id = %s
                    """,
                    (job_id,),
                )
                row = cursor.fetchone()
                return self._row_to_config(row) if row else None

    def upsert_scheduler_job_config(
        self,
        job_id: str,
        *,
        start_time: time,
        end_time: time,
        interval_minutes: int,
        enabled: bool = True,
    ) -> SchedulerJobConfig:
        clean_job_id = (job_id or "").strip()
        if not clean_job_id:
            raise ValueError("job_id 不能为空")
        if interval_minutes <= 0:
            raise ValueError("interval_minutes 必须大于 0")
        if start_time > end_time:
            raise ValueError("start_time 不能晚于 end_time")

        with self._database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO scheduler_job_config
                        (job_id, start_time, end_time, interval_minutes, enabled, updated_at)
                    VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (job_id) DO UPDATE SET
                        start_time = EXCLUDED.start_time,
                        end_time = EXCLUDED.end_time,
                        interval_minutes = EXCLUDED.interval_minutes,
                        enabled = EXCLUDED.enabled,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING job_id, start_time, end_time, interval_minutes, enabled
                    """,
                    (
                        clean_job_id,
                        start_time,
                        end_time,
                        interval_minutes,
                        enabled,
                    ),
                )
                row = cursor.fetchone()

        return self._row_to_config(row)

    def _row_to_config(self, row: dict[str, Any]) -> SchedulerJobConfig:
        return SchedulerJobConfig(
            job_id=str(row["job_id"]),
            start_time=row["start_time"],
            end_time=row["end_time"],
            interval_minutes=int(row["interval_minutes"]),
            enabled=bool(row["enabled"]),
        )
