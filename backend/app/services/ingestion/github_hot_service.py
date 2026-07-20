from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from backend.app.core.config import settings
from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.services.ingestion.source_github import (
    fetch_github_candidate_repos,
    fetch_github_repo_metrics_batch,
    fetch_github_trending_repos,
)

logger = logging.getLogger(__name__)

_PERIOD_TO_DAYS = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
}


def _today_str() -> str:
    tz_name = getattr(settings, "scheduler_timezone", "Asia/Shanghai") or "Asia/Shanghai"
    return datetime.now(ZoneInfo(tz_name)).date().isoformat()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merge_channels(existing: str, new_channel: str) -> str:
    parts = [p.strip() for p in (existing or "").split(",") if p.strip()]
    if new_channel not in parts:
        parts.append(new_channel)
    return ",".join(parts)


def record_github_trending_hits(
    items: List[Dict[str, Any]],
    *,
    period: str,
    observed_date: str | None = None,
    captured_at: str | None = None,
    db: MySQLRepository | None = None,
) -> Dict[str, Any]:
    """Persist structured Trending observations and return canonical repo IDs."""
    normalized_period = (period or "daily").lower().strip()
    if normalized_period not in _PERIOD_TO_DAYS:
        raise ValueError(f"Unsupported period: {period}")
    active_db = db or MySQLRepository()
    active_date = observed_date or _today_str()
    active_captured_at = captured_at or _utcnow()
    repo_ids: List[str] = []
    growth_count = 0
    for item in items:
        full_name = str(item.get("full_name") or item.get("title") or "").strip()
        if not full_name:
            continue
        growth = item.get("period_star_growth")
        if normalized_period == "daily":
            canonical_repo_id = active_db.ensure_github_repo_candidate(
                {
                    "repo_id": item.get("repo_id") or full_name,
                    "full_name": full_name,
                    "title": item.get("title") or full_name,
                    "url": item.get("url") or f"https://github.com/{full_name}",
                    "description": item.get("description") or item.get("summary") or "",
                    "language": item.get("language") or "",
                    "stars": int(item.get("stars") or 0),
                    "source_channels": "trending_daily",
                    "last_snapshot_at": active_captured_at,
                }
            )
            active_db.insert_github_repo_snapshot(
                {
                    "repo_id": canonical_repo_id,
                    "full_name": full_name,
                    "snapshot_date": active_date,
                    "captured_at": active_captured_at,
                    "stars": int(item.get("stars") or 0),
                    "forks": int(item.get("forks") or 0),
                    "watchers": int(item.get("watchers") or 0),
                    "community_metrics_complete": 0,
                    "open_issues": int(item.get("open_issues") or 0),
                    "repo_created_at": item.get("created_at") or "",
                    "repo_pushed_at": item.get("pushed_at") or "",
                }
            )
        else:
            canonical_repo_id = str(item.get("repo_id") or full_name)
        canonical_repo_id = active_db.upsert_github_trending_hit(
            {
                "repo_id": canonical_repo_id,
                "full_name": full_name,
                "period": normalized_period,
                "language": item.get("language") or "",
                "rank": int(item.get("rank") or item.get("rank_in_period") or 999),
                "observed_date": active_date,
                "captured_at": active_captured_at,
                "period_star_growth": int(growth) if growth is not None else None,
                "period_growth_observed_at": active_captured_at if growth is not None else None,
            }
        )
        if canonical_repo_id not in repo_ids:
            repo_ids.append(canonical_repo_id)
        if growth is not None:
            growth_count += 1
    return {
        "period": normalized_period,
        "observed_date": active_date,
        "hits": len(repo_ids),
        "growth_values": growth_count,
        "repo_ids": repo_ids,
    }


def refresh_github_hot_candidates(
    limit: int = 80,
    *,
    observed_date: str | None = None,
) -> Dict[str, Any]:
    """抓取 Trending + Search 候选，并写入 repo candidates / snapshots / trending hits。"""
    db = MySQLRepository()
    resolved_date = observed_date or _today_str()
    captured_at = _utcnow()

    candidate_map: Dict[str, Dict[str, Any]] = {}
    trending_by_period: Dict[str, List[Dict[str, Any]]] = {}

    for period in ("daily", "weekly", "monthly"):
        try:
            repos = fetch_github_trending_repos(period=period, limit=min(limit, 25))
        except Exception as exc:
            logger.warning("[GitHubHot] Trending 抓取失败 period=%s: %s", period, exc)
            repos = []
        trending_by_period[period] = repos

        for repo in repos:
            full_name = str(repo.get("full_name") or "").strip()
            if not full_name:
                continue
            existing = candidate_map.get(full_name) or {}
            candidate_map[full_name] = {
                **repo,
                **existing,
                "repo_id": full_name,
                "source_channels": _merge_channels(
                    str(existing.get("source_channels") or ""),
                    f"trending_{period}",
                ),
                "_community_metrics_complete": False,
            }

    metrics = fetch_github_repo_metrics_batch(list(candidate_map))
    for repo in metrics:
        full_name = str(repo.get("full_name") or "").strip()
        if not full_name or full_name not in candidate_map:
            continue
        source_channels = candidate_map[full_name].get("source_channels", "")
        candidate_map[full_name] = {
            **candidate_map[full_name],
            **repo,
            "repo_id": full_name,
            "source_channels": source_channels,
            "_community_metrics_complete": True,
        }

    try:
        searched = fetch_github_candidate_repos(limit=limit)
    except Exception as exc:
        logger.warning("[GitHubHot] Search 候选抓取失败: %s", exc)
        searched = []

    for repo in searched:
        repo_id = str(repo.get("full_name") or repo.get("repo_id") or "").strip()
        if not repo_id:
            continue
        existing = candidate_map.get(repo_id)
        repo["repo_id"] = repo_id
        repo["_community_metrics_complete"] = True
        repo["source_channels"] = _merge_channels(
            (existing or {}).get("source_channels", ""),
            "search_candidates",
        )
        candidate_map[repo_id] = repo if existing is None else {**existing, **repo}

    repo_count = 0
    snapshot_count = 0
    for repo_id, repo in candidate_map.items():
        channels = repo.get("source_channels", "")
        db.upsert_github_repo_candidate(
            {
                "repo_id": repo_id,
                "full_name": repo.get("full_name") or repo.get("title") or repo_id,
                "title": repo.get("title") or repo.get("full_name") or repo_id,
                "url": repo.get("url") or "",
                "description": repo.get("description") or repo.get("summary") or "",
                "language": repo.get("language") or "",
                "topics_json": __import__("json").dumps(
                    repo.get("topics") or repo.get("tags") or [], ensure_ascii=False
                ),
                "created_at": repo.get("created_at")
                or repo.get("published_date")
                or "",
                "pushed_at": repo.get("pushed_at") or "",
                "stars": int(repo.get("stars") or 0),
                "forks": int(repo.get("forks") or 0),
                "watchers": int(repo.get("watchers") or 0),
                "source_channels": channels,
                "last_snapshot_at": captured_at,
            }
        )
        repo_count += 1

        db.insert_github_repo_snapshot(
            {
                "repo_id": repo_id,
                "snapshot_date": resolved_date,
                "captured_at": captured_at,
                "stars": int(repo.get("stars") or 0),
                "forks": int(repo.get("forks") or 0),
                "watchers": int(repo.get("watchers") or 0),
                "community_metrics_complete": (
                    1 if repo.get("_community_metrics_complete") else 0
                ),
                "open_issues": int(repo.get("open_issues") or 0),
                "repo_created_at": repo.get("created_at")
                or repo.get("published_date")
                or "",
                "repo_pushed_at": repo.get("pushed_at") or "",
            }
        )
        snapshot_count += 1

    hit_results = [
        record_github_trending_hits(
            items,
            period=period,
            observed_date=resolved_date,
            captured_at=captured_at,
            db=db,
        )
        for period, items in trending_by_period.items()
    ]
    hit_count = sum(int(result["hits"]) for result in hit_results)
    growth_count = sum(int(result["growth_values"]) for result in hit_results)

    logger.info(
        "[GitHubHot] 刷新完成：repos=%d snapshots=%d hits=%d growth=%d",
        repo_count,
        snapshot_count,
        hit_count,
        growth_count,
    )
    return {
        "date": resolved_date,
        "repos": repo_count,
        "snapshots": snapshot_count,
        "trending_hits": hit_count,
        "trending_growth_values": growth_count,
        "daily_repo_ids": next(
            (result["repo_ids"] for result in hit_results if result["period"] == "daily"),
            [],
        ),
    }


def get_github_hot_rank(period: str = "daily", limit: int = 10) -> Dict[str, Any]:
    normalized = (period or "daily").lower().strip()
    if normalized not in _PERIOD_TO_DAYS:
        raise ValueError(f"Unsupported period: {period}")

    db = MySQLRepository()
    items = db.get_github_hot_repos(normalized, limit=limit)
    return {
        "period": normalized,
        "window_days": _PERIOD_TO_DAYS[normalized],
        "items": items,
        "total": len(items),
        "snapshot_count": db.get_github_snapshot_count(),
    }
