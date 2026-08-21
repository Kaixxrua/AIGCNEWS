from __future__ import annotations

from typing import Any, Protocol


class IngestionTaskWriter(Protocol):
    """Write boundary for ingestion task lifecycle updates."""

    def create_task(self, task_name: str) -> int: ...

    def finish_task(
        self,
        task_id: int,
        *,
        status: str = "success",
        error_msg: str | None = None,
        item_count: int = 0,
    ) -> None: ...


class LatestTaskReader(Protocol):
    """Read boundary for the latest ingestion task."""

    def get_latest_task(self) -> dict[str, Any] | None: ...


class LatestTaskByNameReader(Protocol):
    """Read boundary for the most recent task with an exact name."""

    def get_latest_task_by_name(self, task_name: str) -> dict[str, Any] | None: ...


class TaskByIdReader(Protocol):
    """Read boundary for a single ingestion task by primary key.

    调度器据此在单源采集完成后回读任务终态：X rolling-window 完整性失败
    会被 orchestrator 记为 failed，调度层据此返回失败进入连续失败告警，
    不再仅凭 ingested_total>0 误判成功。
    """

    def get_task(self, task_id: int) -> dict[str, Any] | None: ...


class RecentTaskReader(Protocol):
    """Read boundary for recent ingestion task metrics."""

    def get_recent_tasks(self, limit: int = 100) -> list[dict[str, Any]]: ...


class MonitorTaskRepository(Protocol):
    """Read-only task query boundary used by monitor endpoints."""

    def list_tasks(
        self,
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]: ...


class IngestionTaskAdminRepository(Protocol):
    """Destructive task administration boundary used by operations."""

    def clear_all_tasks(self) -> int: ...
