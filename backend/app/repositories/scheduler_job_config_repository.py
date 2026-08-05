from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Protocol


@dataclass(frozen=True)
class SchedulerJobConfig:
    """Persistent configuration for a single scheduled job.

    The job executes every ``interval_minutes`` between ``start_time`` and
    ``end_time`` each day. The window is inclusive of the start instant and
    stops scheduling further fires after ``end_time``.
    """

    job_id: str
    start_time: time
    end_time: time
    interval_minutes: int
    enabled: bool = True


class SchedulerJobConfigReader(Protocol):
    def list_scheduler_job_configs(self) -> list[SchedulerJobConfig]: ...

    def get_scheduler_job_config(self, job_id: str) -> SchedulerJobConfig | None: ...


class SchedulerJobConfigManager(SchedulerJobConfigReader, Protocol):
    def upsert_scheduler_job_config(
        self,
        job_id: str,
        *,
        start_time: time,
        end_time: time,
        interval_minutes: int,
        enabled: bool = True,
    ) -> SchedulerJobConfig: ...


class SchedulerJobConfigRepository(SchedulerJobConfigManager, Protocol):
    """Persistence boundary for scheduler job schedules."""
