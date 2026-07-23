from __future__ import annotations

from typing import Any

from backend.app.repositories.mysql_repo import MySQLRepository


class MySQLProjectCatalogRepository:
    """Project catalog adapter for the compatibility MySQL repository."""

    def __init__(self, repository: MySQLRepository | None = None) -> None:
        self._repository = repository if repository is not None else MySQLRepository()

    def find_lexical_candidate_repo_ids(
        self,
        *,
        q: str,
        category: str = "",
        subcategory: str = "",
        language: str = "",
        tag: str = "",
        min_stars: int = 500,
        enriched_only: bool = True,
        limit: int = 200,
    ) -> list[str]:
        return self._repository.find_lexical_candidate_repo_ids(
            q=q,
            category=category,
            subcategory=subcategory,
            language=language,
            tag=tag,
            min_stars=min_stars,
            enriched_only=enriched_only,
            limit=limit,
        )

    def list_projects(
        self,
        *,
        source: str = "all",
        scope: str = "all",
        category: str = "",
        subcategory: str = "",
        q: str = "",
        language: str = "",
        tag: str = "",
        page: int = 1,
        page_size: int = 24,
        sort: str = "stars",
        min_stars: int = 500,
        enriched_only: bool = True,
        user_id: int | None = None,
        favorites_only: bool = False,
        candidate_repo_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        return self._repository.list_projects(
            source=source,
            scope=scope,
            category=category,
            subcategory=subcategory,
            q=q,
            language=language,
            tag=tag,
            page=page,
            page_size=page_size,
            sort=sort,
            min_stars=min_stars,
            enriched_only=enriched_only,
            user_id=user_id,
            favorites_only=favorites_only,
            candidate_repo_ids=candidate_repo_ids,
        )

    def get_project_categories(
        self,
        *,
        source: str = "all",
        min_stars: int = 500,
        enriched_only: bool = True,
        user_id: int | None = None,
        favorites_only: bool = False,
    ) -> dict[str, Any]:
        return self._repository.get_project_categories(
            source=source,
            min_stars=min_stars,
            enriched_only=enriched_only,
            user_id=user_id,
            favorites_only=favorites_only,
        )
