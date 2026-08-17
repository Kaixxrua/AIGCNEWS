from __future__ import annotations

from typing import Any, Protocol


class ProjectAdoptionRepository(Protocol):
    """采纳回执仓储契约：仅追加写入 + 窗口聚合读取。"""

    def record_project_adoption(self, receipt: dict[str, Any]) -> dict[str, Any]: ...

    def get_project_adoption_stats(self, *, since_days: int = 30) -> dict[str, Any]: ...
