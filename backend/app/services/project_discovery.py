from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.services.ingestion.source_github_mcp import search_github_projects_fallback

logger = logging.getLogger(__name__)

PROJECT_FALLBACK_POLICY = "local_first_github_only_when_local_zero"
PROJECT_SORT_CHOICES = {"hot", "stars", "updated", "recent", "name"}
PROJECT_SCOPE_CHOICES = {"all", "today", "recommended"}


def public_project_item(item: dict[str, Any]) -> dict[str, Any]:
    def clipped(value: Any, limit: int) -> str:
        text = str(value or "").strip()
        return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"

    return {
        "id": item.get("id"),
        "full_name": item.get("full_name") or item.get("title") or "",
        "url": item.get("url") or "",
        "description": clipped(item.get("description"), 360),
        "description_zh": clipped(item.get("description_zh"), 360),
        "category": item.get("category") or item.get("category_slug") or "",
        "subcategory": item.get("subcategory") or item.get("subcategory_slug") or "",
        "tags": list(item.get("tags") or [])[:4],
        "topics": list(item.get("topics") or [])[:4],
        "language": item.get("language") or "",
        "stars": int(item.get("stars") or 0),
        "forks": int(item.get("forks") or 0),
        "pushed_at": item.get("pushed_at"),
        "daily_star_growth": int(item.get("daily_star_growth") or 0),
        "daily_growth_available": bool(item.get("daily_growth_available")),
        "hot_score": float(item.get("hot_score") or 0),
        "is_recommended": bool(item.get("is_recommended")),
        "result_origin": item.get("result_origin") or "aigc_news_local",
    }


async def search_projects(
    *,
    query: str,
    mode: Literal["generic", "ai"] = "generic",
    language: str = "",
    category: str = "",
    subcategory: str = "",
    scope: str = "all",
    sort: str | None = None,
    limit: int = 10,
    repository_factory: Any = MySQLRepository,
    fallback_search: Any = search_github_projects_fallback,
) -> dict[str, Any]:
    generic = mode == "generic"
    query = str(query or "").strip()[:120]
    if generic and not query:
        raise ValueError("q is required for generic project search")
    language = str(language or "").strip()[:64]
    category = "" if generic else str(category or "").strip()[:64]
    subcategory = "" if generic else str(subcategory or "").strip()[:64]
    scope = "all" if generic else (scope if scope in PROJECT_SCOPE_CHOICES else "all")
    requested_sort = sort if sort in PROJECT_SORT_CHOICES else ("hot" if scope == "today" else ("recent" if scope == "recommended" else "stars"))
    effective_sort = "hot" if scope == "today" else requested_sort
    limit = max(1, min(int(limit or 10), 20))
    min_stars = 50 if generic else 500

    result = await asyncio.to_thread(
        repository_factory().list_projects,
        source="github",
        scope=scope,
        category=category,
        subcategory=subcategory,
        q=query,
        language=language,
        page=1,
        page_size=limit,
        sort=effective_sort,
        min_stars=min_stars,
        enriched_only=True,
        user_id=None,
    )
    items = [public_project_item(item) for item in result.get("items") or []]
    total = int(result.get("total") or 0)
    base = {
        "items": items,
        "total": total,
        "page": 1,
        "page_size": limit,
        "has_next": limit < total,
        "min_stars": min_stars,
        "scope": scope,
        "category": category,
        "subcategory": subcategory,
        "language": language,
        "q": query,
        "sort": effective_sort,
        "source": "github",
        "search_mode": mode,
        "result_origin": "aigc_news_local",
        "local_total": total,
        "fallback_used": False,
        "fallback_reason": "",
        "fallback_policy": PROJECT_FALLBACK_POLICY,
    }
    if items or scope in {"recommended", "today"}:
        return base

    try:
        fallback = await asyncio.to_thread(
            fallback_search,
            q=query,
            category=category,
            subcategory=subcategory,
            language=language,
            sort=effective_sort,
            limit=limit,
            min_stars=min_stars,
            mode=mode,
        )
    except Exception as exc:
        logger.warning("GitHub project fallback failed: %s", exc)
        return {**base, "fallback_used": True, "fallback_reason": "local_zero_results", "fallback_error": f"GitHub fallback failed: {exc}"}

    fallback_items = [public_project_item(item) for item in fallback.get("items") or []]
    return {
        **base,
        "items": fallback_items,
        "total": int(fallback.get("total") or len(fallback_items)),
        "has_next": False,
        "result_origin": "github_api_fallback" if fallback_items else "aigc_news_local",
        "fallback_used": True,
        "fallback_reason": "local_zero_results",
        "fallback_error": str(fallback.get("error") or ""),
        "github_total_count": int(fallback.get("github_total_count") or 0),
        "fallback_queries": fallback.get("queries") or [],
        "fallback_cache_hit": bool(fallback.get("cache_hit")),
    }
