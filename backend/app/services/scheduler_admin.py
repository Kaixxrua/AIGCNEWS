from __future__ import annotations

"""Administrative control plane for the application scheduler."""

from datetime import datetime, timezone
from typing import Any, Protocol


class ScheduledJob(Protocol):
    id: str
    name: str
    next_run_time: Any
    trigger: Any

    def modify(self, **changes: Any) -> Any: ...


class SchedulerControl(Protocol):
    running: bool

    def get_jobs(self) -> list[ScheduledJob]: ...

    def get_job(self, job_id: str) -> ScheduledJob | None: ...

    def wakeup(self) -> None: ...


class SchedulerAdminService:
    """Project scheduler state and manual trigger operations."""

    def __init__(self, scheduler: SchedulerControl) -> None:
        self._scheduler = scheduler

    def status(self) -> dict[str, Any]:
        jobs = []
        for job in self._scheduler.get_jobs():
            next_run = job.next_run_time.isoformat() if job.next_run_time else None
            jobs.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": next_run,
                    "trigger": str(job.trigger),
                }
            )
        return {
            "running": self._scheduler.running,
            "jobs": jobs,
            "job_count": len(jobs),
        }

    def trigger(self, job_id: str) -> dict[str, str]:
        job = self._scheduler.get_job(job_id)
        if job is None:
            return {"status": "error", "message": f"Job '{job_id}' 不存在。"}

        # APScheduler 3.x 的 next_run_time=None 是 pause 语义（job.pause()
        # 同款）；「立即触发」应把下次点火时间设为现在，点火后 cron 触发器
        # 自动回到常规节奏。
        job.modify(next_run_time=datetime.now(timezone.utc))
        self._scheduler.wakeup()
        return {"status": "triggered", "message": f"Job '{job_id}' 已触发执行。"}
