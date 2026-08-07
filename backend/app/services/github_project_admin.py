from __future__ import annotations

"""Administrative GitHub project maintenance commands."""

import logging
from typing import Any, Optional

from backend.app.repositories.application_repository_factory import (
    ApplicationRepositories,
)

logger = logging.getLogger(__name__)


class GitHubProjectAdminService:
    def __init__(self, repositories: ApplicationRepositories) -> None:
        self._repositories = repositories

    def refresh_hot(self, limit: int) -> None:
        from backend.app.services.ingestion.github_hot_service import (
            refresh_github_hot_candidates,
        )
        from backend.app.services.ingestion.github_project_metrics_service import (
            compute_github_daily_metrics,
        )

        refresh_result = refresh_github_hot_candidates(
            limit=limit,
            db=self._repositories.github_ingestion,
        )
        compute_github_daily_metrics(
            metric_date=refresh_result.get("date"),
            repo_ids=refresh_result.get("daily_repo_ids") or None,
            db=self._repositories.github_ingestion,
        )

    def enrich(
        self,
        limit: int,
        force: bool,
        dry_run: bool,
        retry_failed: bool = True,
        refresh_changed: bool = False,
        concurrency: int = 1,
    ) -> dict[str, Any]:
        from backend.app.services.ingestion.github_project_enricher import (
            enrich_github_projects,
        )

        result = enrich_github_projects(
            limit=limit,
            force=force,
            dry_run=dry_run,
            retry_failed=retry_failed,
            refresh_changed=refresh_changed,
            concurrency=concurrency,
            db=self._repositories.github_enrichment,
        )
        logger.info("[Ops] GitHub 项目库富化任务完成：%s", result)
        return result

    def refresh_metrics(
        self,
        *,
        min_stars: int,
        limit: int,
        metric_date: Optional[str],
        dry_run: bool,
    ) -> dict[str, Any]:
        from backend.app.services.ingestion.github_project_metrics_service import (
            refresh_and_compute_github_project_metrics,
        )

        result = refresh_and_compute_github_project_metrics(
            min_stars=min_stars,
            limit=limit,
            metric_date=metric_date,
            dry_run=dry_run,
            db=self._repositories.github_ingestion,
        )
        logger.info("[Ops] GitHub 项目每日指标刷新任务完成：%s", result)
        return result

    def recompute_metrics(
        self,
        *,
        metric_date: Optional[str],
        min_stars: int,
    ) -> dict[str, Any]:
        from backend.app.services.ingestion.github_project_metrics_service import (
            compute_github_daily_metrics,
        )

        return compute_github_daily_metrics(
            metric_date=metric_date,
            min_stars=min_stars,
            db=self._repositories.github_ingestion,
        )
