"""GitHub 新仓快车道：每 15 分钟把近几天新建、已越过 300 星的仓库立即收进项目库。

每日流水线（02:00）的全量爬取只看得到那一刻已越线的仓库；当天稍晚才建仓
或才越线的项目要等到次日凌晨才入库，两小时指标刷新只刷已知候选、不做
发现（2026-09 AIHOT 即此例：09-29 07:40 建仓，当天冲到上千星仍未收录）。
快车道补上这段空窗：只搜 created 近 7 天、stars>=300 的小结果集（2026-09
实测约 50 条，1–2 个搜索请求），对命中项立即刷新当天快照、按子集重算
当天指标。门槛与 channel 标记沿用每日增长观察仓，不引入新的候选口径；
富化（决定对外可见）由调度层在同一把 GitHub 锁内顺带补跑。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict

from backend.app.repositories.project_write_repository import (
    GitHubProjectIngestionRepository,
)
from backend.app.services.ingestion.github_project_enricher import (
    DEFAULT_MIN_STARS,
    GROWTH_OBSERVE_CHANNEL,
    GROWTH_OBSERVE_MIN_STARS,
    _bootstrap_github_readmes,
)
from backend.app.services.ingestion.github_project_metrics_service import (
    current_github_metric_date,
    refresh_and_compute_github_target_metrics,
)
from backend.app.services.ingestion.github_search_crawl import crawl_github_search

logger = logging.getLogger(__name__)

# created 窗口：覆盖绝大多数“新仓暴涨”；更早建仓、今天才越线的仓库
# 仍由次日全量爬取兜底。
FAST_LANE_CREATED_WINDOW_DAYS = 7
# 结果集正常只有几十条，上限仅防刷星潮等异常把一轮拖长
FAST_LANE_CRAWL_LIMIT = 1000


def run_github_fast_lane(
    *,
    ingestion: GitHubProjectIngestionRepository,
    corroborated_repo_ids: set[str] | None = None,
    created_window_days: int = FAST_LANE_CREATED_WINDOW_DAYS,
) -> Dict[str, Any]:
    """发现 → 当天快照 → 子集指标；返回运行摘要（不含富化）。"""
    today = date.fromisoformat(current_github_metric_date())
    crawl = crawl_github_search(
        min_stars=GROWTH_OBSERVE_MIN_STARS,
        max_stars=0,
        limit=FAST_LANE_CRAWL_LIMIT,
        # created 按 UTC 日期匹配；调度时区（UTC+8）的今天总不早于 UTC 今天
        created_start=today - timedelta(days=max(1, int(created_window_days))),
        created_end=today,
        channel=GROWTH_OBSERVE_CHANNEL,
        ingestion=ingestion,
        collect_upserted=True,
    )
    hits = crawl.pop("upserted_candidates", [])
    new_repo_ids = crawl.pop("new_repo_ids", [])
    metrics = refresh_and_compute_github_target_metrics(
        targets=hits,
        min_stars=GROWTH_OBSERVE_MIN_STARS,
        corroborated_repo_ids=corroborated_repo_ids,
        db=ingestion,
    )
    # 空描述的越线新仓先补 README 再富化，否则富化只能凭仓库名瞎猜，
    # 且成功结果不会重做
    readme_candidates = sum(
        1
        for item in hits
        if int(item.get("stars") or 0) >= DEFAULT_MIN_STARS
        and not str(item.get("description") or "").strip()
    )
    summary = {
        "status": "success",
        "created_window_days": created_window_days,
        "hits": len(hits),
        "new_candidates": len(new_repo_ids),
        # 日志里直接可见本轮新发现了谁；上限防异常潮把日志撑爆
        "new_repo_ids": new_repo_ids[:20],
        "readme_candidates": readme_candidates,
        "api_requests": crawl.get("api_requests"),
        "refresh": metrics.get("refresh"),
        "metrics": metrics.get("metrics"),
    }
    logger.info("[GitHubFastLane] 本轮完成：%s", summary)
    return summary


def hydrate_github_readmes(semantic_sources: Any) -> Dict[str, Any]:
    """富化前补 README，口径与每日流水线一致（仅空描述、越过富化门槛的仓库）。"""
    return _bootstrap_github_readmes(
        semantic_sources=semantic_sources,
        min_stars=DEFAULT_MIN_STARS,
    )
