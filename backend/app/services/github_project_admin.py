from __future__ import annotations

"""Administrative GitHub project maintenance commands."""

import logging
from datetime import date, timedelta
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

    def backfill_suspicion(
        self,
        *,
        days: int,
        min_stars: int,
    ) -> dict[str, Any]:
        """回放近 N 天反作弊打标：逐日拉跨渠道佐证并重算当日指标。

        指标重算对相同快照输入是确定性的：suspicion 三字段随新逻辑落库（含
        历史行的旧默认值被覆盖为真实判定），hot_score 按当前算法重写，
        可疑增长降权也随之生效。
        """
        from backend.app.services.ingestion.github_project_metrics_service import (
            compute_github_daily_metrics,
            corroboration_window,
            current_github_metric_date,
        )

        days = max(1, min(int(days or 1), 90))
        today = date.fromisoformat(current_github_metric_date())
        per_day: list[dict[str, Any]] = []
        for offset in range(days - 1, -1, -1):
            metric_date = (today - timedelta(days=offset)).isoformat()
            since, until = corroboration_window(metric_date)
            try:
                corroborated = self._repositories.documents.list_github_repo_mentions(
                    since_date=since,
                    until_date=until,
                )
            except Exception as exc:  # noqa: BLE001 - 单日佐证失败不中断回放
                logger.warning(
                    "[Ops] 反作弊佐证查询失败（%s 按无佐证打标）: %s", metric_date, exc
                )
                corroborated = None
            result = compute_github_daily_metrics(
                metric_date=metric_date,
                min_stars=min_stars,
                corroborated_repo_ids=corroborated,
                db=self._repositories.github_ingestion,
            )
            per_day.append(
                {
                    "metric_date": metric_date,
                    "rows": result.get("rows"),
                    "suspicious": result.get("suspicious"),
                    "demoted": result.get("demoted"),
                    "corroborated": result.get("corroborated"),
                    "corroboration_available": corroborated is not None,
                }
            )
        summary = {
            "status": "success",
            "days": days,
            "suspicious_total": sum(int(day.get("suspicious") or 0) for day in per_day),
            "per_day": per_day,
        }
        logger.info("[Ops] GitHub 反作弊打标回放完成：%s", summary)
        return summary
