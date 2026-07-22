from __future__ import annotations

from typing import Any, Protocol


class MonitorTaskRepository(Protocol):
    """Read-only task query boundary used by monitor endpoints."""

    def list_tasks(
        self,
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]: ...
