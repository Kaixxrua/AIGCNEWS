from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from backend.app.repositories.mysql_repo import MySQLRepository
from backend.app.services.ingestion.source_github_mcp import search_github_projects_fallback
from backend.app.services.search_semantics import normalize_search_query

logger = logging.getLogger(__name__)

PROJECT_FALLBACK_POLICY = "local_first_github_only_when_semantics_preserved"
PROJECT_SORT_CHOICES = {"hot", "stars", "updated", "recent", "name"}
PROJECT_SCOPE_CHOICES = {"all", "today", "recommended"}
_FALLBACK_SORTS = {"stars", "updated"}


def _clipped(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _bounded_strings(value: Any, max_items: int = 4) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    items: list[str] = []
    for raw in value:
        item = _clipped(raw, 40)
        if item and item not in items:
            items.append(item)
        if len(items) >= max_items:
            break
    return items


def public_project_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "full_name": _clipped(item.get("full_name") or item.get("title"), 160),
        "url": _clipped(item.get("url"), 500),
        "description": _clipped(item.get("description"), 180),
        "description_zh": _clipped(item.get("description_zh"), 80),
        "category_slug": _clipped(item.get("category_slug") or item.get("category"), 64),
        "category_name": _clipped(item.get("category_name"), 80),
        "subcategory_slug": _clipped(item.get("subcategory_slug") or item.get("subcategory"), 64),
        "subcategory_name": _clipped(item.get("subcategory_name"), 80),
        "tags": _bounded_strings(item.get("tags")),
        "topics": _bounded_strings(item.get("topics")),
        "language": _clipped(item.get("language"), 64),
        "stars": int(item.get("stars") or 0),
        "forks": int(item.get("forks") or 0),
        "pushed_at": item.get("pushed_at"),
        "daily_star_growth": int(item.get("daily_star_growth") or 0),
        "daily_growth_available": bool(item.get("daily_growth_available")),
        "hot_score": float(item.get("hot_score") or 0),
        "is_recommended": bool(item.get("is_recommended")),
        "result_origin": _clipped(item.get("result_origin") or "aigc_news_local", 40),
    }


def resolve_project_sort(scope: str, requested_sort: str | None) -> str:
    clean_scope = scope if scope in PROJECT_SCOPE_CHOICES else "all"
    if clean_scope == "today":
        return "hot"
    if requested_sort in PROJECT_SORT_CHOICES:
        return requested_sort
    return "recent" if clean_scope == "recommended" else "stars"


async def search_projects(
    *,
    query: str,
    mode: Literal["generic", "ai"] = "generic",
    language: str = "",
    category: str = "",
    subcategory: str = "",
    scope: str = "all",
    sort: str | None = None,
    page: int = 1,
    limit: int = 10,
    repository_factory: Any = MySQLRepository,
    fallback_search: Any = search_github_projects_fallback,
) -> dict[str, Any]:
    generic = mode == "generic"
    query = normalize_search_query(str(query or ""))[:120]
    if generic and not query:
        raise ValueError("q is required for generic project search")
    language = str(language or "").strip()[:64]
    category = "" if generic else str(category or "").strip()[:64]
    subcategory = "" if generic else str(subcategory or "").strip()[:64]
    scope = "all" if generic else (scope if scope in PROJECT_SCOPE_CHOICES else "all")
    effective_sort = resolve_project_sort(scope, sort)
    page = max(1, int(page or 1))
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
        page=page,
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
        "page": page,
        "page_size": limit,
        "has_next": page * limit < total,
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
        "fallback_skipped_reason": "",
        "fallback_policy": PROJECT_FALLBACK_POLICY,
    }
    if total > 0:
        return base
    if page != 1:
        return {**base, "fallback_skipped_reason": "fallback_is_first_page_only"}
    if scope != "all":
        return {**base, "fallback_skipped_reason": "scope_requires_local_metrics"}
    if category or subcategory:
        return {**base, "fallback_skipped_reason": "taxonomy_filter_requires_local_classification"}
    if effective_sort not in _FALLBACK_SORTS:
        return {**base, "fallback_skipped_reason": "sort_not_equivalent_on_github_search"}

    try:
        fallback = await asyncio.to_thread(
            fallback_search,
            q=query,
            category="",
            subcategory="",
            language=language,
            sort=effective_sort,
            limit=limit,
            min_stars=min_stars,
            mode=mode,
        )
    except Exception as exc:
        logger.warning("GitHub project fallback failed: %s", exc)
        return {
            **base,
            "fallback_used": True,
            "fallback_reason": "local_zero_results",
            "fallback_error": f"GitHub fallback failed: {exc}",
        }

    fallback_items = [public_project_item(item) for item in fallback.get("items") or []]
    return {
        **base,
        "items": fallback_items,
        "total": len(fallback_items),
        "has_next": False,
        "result_origin": "github_api_fallback" if fallback_items else "aigc_news_local",
        "fallback_used": True,
        "fallback_reason": "local_zero_results",
        "fallback_error": str(fallback.get("error") or ""),
        "github_total_count": int(fallback.get("github_total_count") or 0),
        "fallback_queries": fallback.get("queries") or [],
        "fallback_cache_hit": bool(fallback.get("cache_hit")),
    }
