from __future__ import annotations

"""Administrative GitHub project recommendation commands."""

import asyncio
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from backend.app.core.auth import extract_user_id


class RecommendationWriter(Protocol):
    def recommend_github_project(
        self,
        *,
        repo_id: str = "",
        full_name: str = "",
        recommended_by_user_id: int | None = None,
    ) -> dict[str, Any]: ...

    def unrecommend_github_project(
        self,
        *,
        repo_id: str | None = None,
        full_name: str = "",
    ) -> dict[str, Any]: ...


class EnrichmentStatusReader(Protocol):
    def get_github_project_enrichment_status(
        self,
        *,
        min_stars: int = 500,
    ) -> dict[str, Any]: ...

    def list_github_project_enrichment_pages(
        self,
        *,
        unprocessable_page: int = 1,
        retained_page: int = 1,
        page_size: int = 15,
        min_stars: int = 500,
    ) -> dict[str, Any]: ...


class GitHubCatalogTotalReader(Protocol):
    async def github_library_total(self) -> int: ...


class GitHubProjectAdminValidationError(ValueError):
    pass


class GitHubProjectAdminNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class RecommendationOutcome:
    message: str
    result: Mapping[str, Any]


class GitHubProjectRecommendationAdminService:
    def __init__(
        self,
        recommendations: RecommendationWriter,
        enrichment_status: EnrichmentStatusReader,
        catalog: GitHubCatalogTotalReader | None = None,
    ) -> None:
        self._recommendations = recommendations
        self._enrichment_status = enrichment_status
        self._catalog = catalog

    async def recommend(
        self,
        *,
        repo_id: str,
        full_name: str,
        admin_identity: Mapping[str, Any] | None,
    ) -> RecommendationOutcome:
        admin_user_id = extract_user_id(admin_identity)
        try:
            result = await asyncio.to_thread(
                self._recommendations.recommend_github_project,
                repo_id=repo_id,
                full_name=full_name,
                recommended_by_user_id=admin_user_id,
            )
        except ValueError as exc:
            raise GitHubProjectAdminValidationError(str(exc)) from exc
        except LookupError as exc:
            raise GitHubProjectAdminNotFoundError(str(exc)) from exc
        return RecommendationOutcome(message="已加入站长推荐。", result=result)

    async def unrecommend(
        self,
        *,
        repo_id: str | None,
        full_name: str,
    ) -> RecommendationOutcome:
        try:
            result = await asyncio.to_thread(
                self._recommendations.unrecommend_github_project,
                repo_id=repo_id,
                full_name=full_name,
            )
        except ValueError as exc:
            raise GitHubProjectAdminValidationError(str(exc)) from exc
        except LookupError as exc:
            raise GitHubProjectAdminNotFoundError(str(exc)) from exc
        message = (
            "已取消站长推荐。"
            if result.get("removed")
            else "该项目当前不是站长推荐。"
        )
        return RecommendationOutcome(message=message, result=result)

    async def get_enrichment_pages(
        self,
        *,
        unprocessable_page: int = 1,
        retained_page: int = 1,
        page_size: int = 15,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._enrichment_status.list_github_project_enrichment_pages,
            unprocessable_page=unprocessable_page,
            retained_page=retained_page,
            page_size=page_size,
        )

    async def get_enrichment_status(self) -> dict[str, Any]:
        status = await asyncio.to_thread(
            self._enrichment_status.get_github_project_enrichment_status
        )
        if self._catalog is not None:
            # 与首页 source_counts.github 复用同一目录查询口径，避免监控页把
            # 当前队列进度误当成项目库总量。
            status["github_library_total"] = await self._catalog.github_library_total()
        # 附带本进程富化批处理运行标记，供运维面板在刷新页面后仍能展示「终止」入口
        from backend.app.services.ingestion.github_project_enricher import (
            github_enrichment_batch_running,
        )

        status["running"] = github_enrichment_batch_running()
        return status
