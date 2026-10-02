"""项目库榜单行情：近 N 天的星标与日增，以及今日热榜的昨日名次。

日期口径与今日热榜一致：今天的指标还没落库（约 02:15 首轮之前）时沿用昨天，只回退一天。
昨日名次取那一天的收盘热榜（看板日榜同一查询、同一排序），只排前 RANK_DEPTH 名，
之外的仓库没有昨日名次，前端记作新上榜。
"""

from __future__ import annotations

import asyncio
import time
from datetime import date, timedelta
from typing import Any, Callable

from backend.app.domain.project_visibility import PUBLIC_PROJECT_MIN_STARS
from backend.app.repositories.postgres_github_project_trends import (
    PostgresGitHubProjectTrendRepository,
    business_today,
)
from backend.app.repositories.project_catalog import ProjectCatalogRepository
from backend.app.repositories.project_catalog_factory import (
    get_project_catalog_repository,
)

__all__ = ["RANK_DEPTH", "TRENDS_MAX_REPOS", "ProjectTrendsService"]

TRENDS_MAX_REPOS = 60
RANK_DEPTH = 200
# 昨天的收盘榜过了零点基本不再变：同一天的名次在进程里留十分钟，翻页、换分类不必每次重排。
_RANKS_TTL_SECONDS = 600.0


class ProjectTrendsService:
    def __init__(
        self,
        trend_repository_factory: Callable[[], Any] = PostgresGitHubProjectTrendRepository,
        catalog_repository_factory: Callable[[], ProjectCatalogRepository] = get_project_catalog_repository,
        *,
        today: Callable[[], date] = business_today,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._trend_repository_factory = trend_repository_factory
        self._catalog_repository_factory = catalog_repository_factory
        self._today = today
        self._clock = clock
        self._ranks: tuple[str, float, dict[str, int]] | None = None

    async def trends(self, repo_ids: list[str], *, days: int, with_ranks: bool) -> dict[str, Any]:
        repository = self._trend_repository_factory()
        today = self._today()
        latest = await asyncio.to_thread(
            repository.latest_metric_date,
            start=(today - timedelta(days=1)).isoformat(),
            end=today.isoformat(),
        )
        metric_date = date.fromisoformat(latest) if latest else today
        rows = await asyncio.to_thread(
            repository.daily_points,
            repo_ids,
            start=(metric_date - timedelta(days=days - 1)).isoformat(),
            end=metric_date.isoformat(),
        )
        points: dict[str, list[dict[str, Any]]] = {repo_id: [] for repo_id in repo_ids}
        for row in rows:
            bucket = points.get(str(row.get("repo_id") or ""))
            if bucket is None:
                continue
            bucket.append({
                "date": str(row.get("metric_date") or ""),
                "stars": int(row.get("stars") or 0),
                # 那天没有可信日增（缺前一天快照等）时留空，火花线画成空位而不是 0。
                "gain": int(row.get("daily_star_growth") or 0) if row.get("daily_growth_available") else None,
            })
        result: dict[str, Any] = {
            "metric_date": metric_date.isoformat(),
            "days": days,
            "items": {repo_id: {"points": series} for repo_id, series in points.items()},
        }
        if with_ranks:
            previous_date = (metric_date - timedelta(days=1)).isoformat()
            ranks = await self._ranks_for(previous_date)
            result["previous_date"] = previous_date
            for repo_id, item in result["items"].items():
                item["previous_rank"] = ranks.get(repo_id)
        return result

    async def _ranks_for(self, metric_date: str) -> dict[str, int]:
        cached = self._ranks
        now = self._clock()
        if cached is not None and cached[0] == metric_date and now - cached[1] < _RANKS_TTL_SECONDS:
            return cached[2]
        rows = await asyncio.to_thread(
            self._catalog_repository_factory().list_github_hot_for_date,
            metric_date=metric_date,
            limit=RANK_DEPTH,
            min_stars=PUBLIC_PROJECT_MIN_STARS,
            enriched_only=True,
        )
        ranks: dict[str, int] = {}
        for row in rows:
            repo_id = str(row.get("repo_id") or "")
            if repo_id and repo_id not in ranks:
                ranks[repo_id] = len(ranks) + 1
        self._ranks = (metric_date, now, ranks)
        return ranks
