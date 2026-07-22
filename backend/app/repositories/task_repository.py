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


class MonitorTaskRepository(Protocol):
    """Read-only task query boundary used by monitor endpoints."""

    def list_tasks(
        self,
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]: ...
