from __future__ import annotations

from typing import Any, Callable

from backend.app.repositories.postgres_project_adoption_repository import (
    get_project_adoption_repository,
)
from backend.app.repositories.project_adoption_repository import (
    ProjectAdoptionRepository,
)

ADOPTION_DECISIONS = ("adopted", "reference_only", "declined")


def adoption_rate(totals: dict[str, int]) -> float:
    """复用率 = 采纳 / 全部回执；无回执时为 0.0 而非除零。"""
    total = sum(totals.values())
    if total <= 0:
        return 0.0
    return round(totals.get("adopted", 0) / total, 4)


class ProjectAdoptionService:
    """采纳回执编排入口（REST / MCP 共用）。

    与 ProjectCatalogQueryService 同一模式：仓储经工厂按次惰性解析，
    测试可注入假仓储工厂替换。
    """

    def __init__(
        self,
        repository_factory: Callable[[], ProjectAdoptionRepository] = get_project_adoption_repository,
    ) -> None:
        self._repository_factory = repository_factory

    def record(self, receipt: dict[str, Any]) -> dict[str, Any]:
        decision = receipt.get("decision")
        if decision not in ADOPTION_DECISIONS:
            raise ValueError(f"decision 必须是 {list(ADOPTION_DECISIONS)} 之一。")
        repository = self._repository_factory()
        recorded = repository.record_project_adoption(receipt)
        recorded["stats"] = self._with_rate(repository.get_project_adoption_stats())
        return recorded

    def stats(self, *, since_days: int = 30) -> dict[str, Any]:
        repository = self._repository_factory()
        return self._with_rate(repository.get_project_adoption_stats(since_days=since_days))

    @staticmethod
    def _with_rate(stats: dict[str, Any]) -> dict[str, Any]:
        stats["window_adoption_rate"] = adoption_rate(stats.get("window") or {})
        stats["total_adoption_rate"] = adoption_rate(stats.get("total") or {})
        return stats
