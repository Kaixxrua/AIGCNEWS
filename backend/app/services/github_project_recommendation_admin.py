from __future__ import annotations

"""Administrative GitHub project recommendation commands."""

import asyncio
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


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
    ) -> None:
        self._recommendations = recommendations
        self._enrichment_status = enrichment_status

    async def recommend(
        self,
        *,
        repo_id: str,
        full_name: str,
        admin_identity: Mapping[str, Any] | None,
    ) -> RecommendationOutcome:
        admin_user_id = _admin_user_id(admin_identity)
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

    async def get_enrichment_status(self) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._enrichment_status.get_github_project_enrichment_status
        )


def _admin_user_id(identity: Mapping[str, Any] | None) -> int | None:
    if not identity:
        return None
    raw_user_id = identity.get("user_id") or identity.get("id") or identity.get("sub")
    try:
        return int(raw_user_id) if raw_user_id else None
    except (TypeError, ValueError):
        return None
