from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable

from backend.app.repositories.project_catalog import ProjectCatalogRepository
from backend.app.repositories.project_catalog_factory import (
    get_project_catalog_repository,
)
from backend.app.services.ingestion.source_github_mcp import PUBLIC_PROJECT_MIN_STARS
from backend.app.services.project_discovery import resolve_project_sort

__all__ = [
    "PUBLIC_PROJECT_MIN_STARS",
    "ProjectCatalogPage",
    "ProjectCatalogQueryService",
]


@dataclass(frozen=True)
class ProjectCatalogPage:
    """公共项目库分页结果，附带回显所需的生效排序。"""

    result: dict[str, Any]
    effective_sort: str


class ProjectCatalogQueryService:
    """公共项目目录查询编排入口（REST / MCP / dashboard 共用）。

    统一承载 min_stars 收录门槛策略与 sort 解析，替代路由/MCP 层直调
    仓储全局工厂；仓储经工厂按次惰性解析，保持每次查询新建适配器的
    既有语义，测试可注入假仓储工厂替换。
    """

    def __init__(
        self,
        repository_factory: Callable[[], ProjectCatalogRepository] = get_project_catalog_repository,
    ) -> None:
        self._repository_factory = repository_factory

    @property
    def min_stars(self) -> int:
        """公共项目库最低 star 门槛（唯一定义见 PUBLIC_PROJECT_MIN_STARS）。"""
        return PUBLIC_PROJECT_MIN_STARS

    async def list_public_projects(
        self,
        *,
        scope: str,
        category: str,
        subcategory: str,
        q: str,
        language: str,
        page: int,
        page_size: int,
        sort: str | None,
        user_id: int | None,
    ) -> ProjectCatalogPage:
        effective_sort = resolve_project_sort(
            scope, sort, has_query=bool(q), prefer_relevance=True
        )
        result = await asyncio.to_thread(
            self._repository_factory().list_projects,
            source="github",
            scope=scope,
            category=category,
            subcategory=subcategory,
            q=q,
            language=language,
            page=page,
            page_size=page_size,
            sort=effective_sort,
            min_stars=PUBLIC_PROJECT_MIN_STARS,
            enriched_only=True,
            user_id=user_id,
        )
        return ProjectCatalogPage(result=result, effective_sort=effective_sort)

    async def get_public_categories(self) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._repository_factory().get_project_categories,
            source="github",
            min_stars=PUBLIC_PROJECT_MIN_STARS,
            enriched_only=True,
        )

    async def github_library_total(self) -> int:
        """Return the public GitHub catalog total used by dashboard source counts."""
        return int(
            await asyncio.to_thread(
                self._repository_factory().count_github_catalog_candidates,
                min_stars=PUBLIC_PROJECT_MIN_STARS,
            )
            or 0
        )
