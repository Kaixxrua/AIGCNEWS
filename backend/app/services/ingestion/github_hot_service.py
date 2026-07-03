from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Dict, List

from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.services.ingestion.source_github import (
    fetch_github_candidate_repos,
    fetch_github_repo_metadata,
    fetch_github_trending_repos,
)

logger = logging.getLogger(__name__)

_PERIOD_TO_DAYS = {
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
}


def _today_str() -> str:
    return date.today().isoformat()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merge_channels(existing: str, new_channel: str) -> str:
    parts = [p.strip() for p in (existing or "").split(",") if p.strip()]
    if new_channel not in parts:
        parts.append(new_channel)
    return ",".join(parts)


def refresh_github_hot_candidates(limit: int = 80) -> Dict[str, Any]:
    """抓取 Trending + Search 候选，并写入 repo candidates / snapshots / trending hits。"""
    db = MySQLRepository()
    observed_date = _today_str()
    captured_at = _utcnow()

    candidate_map: Dict[str, Dict[str, Any]] = {}
    trending_hits: List[Dict[str, Any]] = []

    for period in ("daily", "weekly", "monthly"):
        try:
            repos = fetch_github_trending_repos(period=period, limit=min(limit, 25))
        except Exception as exc:
            logger.warning("[GitHubHot] Trending 抓取失败 period=%s: %s", period, exc)
            repos = []

        for repo in repos:
            full_name = str(repo.get("full_name") or "").strip()
            if not full_name:
                continue
            repo_id = full_name
            if repo_id not in candidate_map:
                meta = fetch_github_repo_metadata(full_name)
                if not meta:
                    continue
                meta["repo_id"] = repo_id
                candidate_map[repo_id] = meta
            candidate_map[repo_id]["source_channels"] = _merge_channels(
                candidate_map[repo_id].get("source_channels", ""),
                f"trending_{period}",
            )
            trending_hits.append(
                {
                    "repo_id": repo_id,
                    "full_name": full_name,
                    "period": period,
                    "language": candidate_map[repo_id].get("language", ""),
                    "rank": int(repo.get("rank") or 999),
                    "observed_date": observed_date,
                    "captured_at": captured_at,
                }
            )

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
                "snapshot_date": observed_date,
                "captured_at": captured_at,
                "stars": int(repo.get("stars") or 0),
                "forks": int(repo.get("forks") or 0),
                "watchers": int(repo.get("watchers") or 0),
                "open_issues": int(repo.get("open_issues") or 0),
                "repo_created_at": repo.get("created_at")
                or repo.get("published_date")
                or "",
                "repo_pushed_at": repo.get("pushed_at") or "",
            }
        )
        snapshot_count += 1

    for hit in trending_hits:
        db.upsert_github_trending_hit(hit)

    logger.info(
        "[GitHubHot] 刷新完成：repos=%d snapshots=%d hits=%d",
        repo_count,
        snapshot_count,
        len(trending_hits),
    )
    return {
        "date": observed_date,
        "repos": repo_count,
        "snapshots": snapshot_count,
        "trending_hits": len(trending_hits),
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
