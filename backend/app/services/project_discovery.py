from __future__ import annotations

import asyncio
import inspect
import logging
import re
from typing import Any, Literal

from backend.app.core.config import settings
from backend.app.repositories.project_catalog import ProjectLexicalCandidateLanes
from backend.app.repositories.project_catalog_factory import get_project_catalog_repository
from backend.app.services.ingestion.source_github_mcp import (
    PUBLIC_PROJECT_MIN_STARS,
    search_github_projects_fallback,
)
from backend.app.services.project_reranker import get_project_reranker
from backend.app.services.project_search_ranking import (
    ProjectCandidateSearchResult,
    rank_legacy_project_candidate_ids,
    rank_v2_project_candidate_ids,
)
from backend.app.services.project_semantic_search import get_project_semantic_search
from backend.app.services.search_semantics import (
    ProjectSearchIntent,
    build_client_project_search_intent,
    build_project_search_intent,
    normalize_search_query,
)

logger = logging.getLogger(__name__)

PROJECT_FALLBACK_POLICY = "local_first_github_only_when_semantics_preserved"
PROJECT_SORT_CHOICES = {"relevance", "hot", "stars", "updated", "recent", "name"}
PROJECT_SCOPE_CHOICES = {"all", "today", "recommended"}
_FALLBACK_SORTS = {"relevance", "stars", "updated"}
_EXACT_REPO_QUERY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


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


def _project_reranker_query(query: str, intent: ProjectSearchIntent, *, enriched: bool) -> str:
    if not enriched:
        return query
    sections = [query]
    hints = (
        ("intent", (intent.intent_class,)),
        ("topics", intent.topics),
        ("artifact types", intent.artifact_types),
        ("must have", intent.must_have),
        ("should have", intent.should_have),
    )
    for label, values in hints:
        if values:
            sections.append(f"{label}: {', '.join(values)}")
    return _clipped("; ".join(sections), 500)


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


def _declared_callable(value: Any, name: str) -> Any | None:
    try:
        inspect.getattr_static(value, name)
    except AttributeError:
        return None
    candidate = getattr(value, name, None)
    return candidate if callable(candidate) else None


def resolve_project_sort(
    scope: str,
    requested_sort: str | None,
    *,
    has_query: bool = False,
    prefer_relevance: bool = False,
) -> str:
    clean_scope = scope if scope in PROJECT_SCOPE_CHOICES else "all"
    if clean_scope == "today":
        return "hot"
    if requested_sort in PROJECT_SORT_CHOICES:
        if requested_sort == "relevance" and not has_query:
            return "recent" if clean_scope == "recommended" else "stars"
        return requested_sort
    if has_query and prefer_relevance:
        return "relevance"
    return "recent" if clean_scope == "recommended" else "stars"


async def search_projects(
    *,
    query: str,
    mode: Literal["generic", "ai"] = "generic",
    language: str = "",
    client_intent: dict[str, Any] | None = None,
    category: str = "",
    subcategory: str = "",
    scope: str = "all",
    sort: str | None = None,
    page: int = 1,
    limit: int = 10,
    repository_factory: Any | None = None,
    fallback_search: Any = search_github_projects_fallback,
    semantic_search_factory: Any | None = None,
    reranker_factory: Any | None = None,
) -> dict[str, Any]:
    generic = mode == "generic"
    query = normalize_search_query(str(query or ""))[:120]
    if generic and not query:
        raise ValueError("q is required for generic project search")
    language = str(language or "").strip()[:64]
    category = "" if generic else str(category or "").strip()[:64]
    subcategory = "" if generic else str(subcategory or "").strip()[:64]
    scope = "all" if generic else (scope if scope in PROJECT_SCOPE_CHOICES else "all")
    effective_sort = resolve_project_sort(
        scope,
        sort,
        has_query=bool(query),
        prefer_relevance=mode == "ai",
    )
    page = max(1, int(page or 1))
    limit = max(1, min(int(limit or 10), 20))
    min_stars = PUBLIC_PROJECT_MIN_STARS
    intent = build_project_search_intent(query)
    client_intent_used = bool(
        client_intent
        and mode == "ai"
        and query
        and effective_sort == "relevance"
    )
    if client_intent_used:
        intent = build_client_project_search_intent(query, client_intent or {})
    lexical_query = " ".join(intent.lexical_terms) or intent.normalized_query

    repository = (
        repository_factory()
        if repository_factory is not None
        else get_project_catalog_repository()
    )
    hybrid_attempted = False
    result: dict[str, Any]
    lexical_candidate_search = _declared_callable(
        repository,
        "find_lexical_candidate_repo_ids",
    )
    lexical_lane_search = _declared_callable(
        repository,
        "find_lexical_candidate_lanes",
    )
    strategy = str(getattr(settings, "project_ai_search_strategy", "legacy") or "legacy").strip().lower()
    if strategy not in {"legacy", "shadow", "v2"}:
        strategy = "legacy"
    if mode == "ai" and query and effective_sort == "relevance" and callable(lexical_candidate_search):
        hybrid_attempted = True
        use_lanes = strategy in {"shadow", "v2"} and callable(lexical_lane_search)
        lexical_task = asyncio.to_thread(
            lexical_lane_search if use_lanes else lexical_candidate_search,
            q=lexical_query,
            category=category,
            subcategory=subcategory,
            language=language,
            min_stars=min_stars,
            enriched_only=True,
            **({"strict_limit": 150, "relaxed_limit": 150} if use_lanes else {"limit": 150}),
        )
        semantic_task = None
        if settings.project_semantic_search_enabled:
            semantic_search = (
                semantic_search_factory()
                if semantic_search_factory is not None
                else get_project_semantic_search()
            )
            semantic_task = asyncio.wait_for(
                asyncio.to_thread(semantic_search.search_repo_ids, intent),
                timeout=max(0.1, float(settings.project_semantic_query_timeout_seconds)),
            )
        tasks = [lexical_task, *([semantic_task] if semantic_task is not None else [])]
        candidate_results = await asyncio.gather(*tasks, return_exceptions=True)
        lexical_repo_ids = candidate_results[0] if not isinstance(candidate_results[0], Exception) else []
        semantic_hits = (
            candidate_results[1]
            if len(candidate_results) > 1 and not isinstance(candidate_results[1], Exception)
            else []
        )
        semantic_repo_ids = tuple(
            str(hit.repo_id) for hit in semantic_hits if getattr(hit, "repo_id", "")
        )
        if use_lanes and isinstance(lexical_repo_ids, ProjectLexicalCandidateLanes):
            lanes = lexical_repo_ids
            legacy_lexical_repo_ids = tuple(candidate.repo_id for candidate in lanes.strict)
        else:
            lanes = None
            legacy_lexical_repo_ids = tuple(str(repo_id) for repo_id in lexical_repo_ids)
        candidate_search = ProjectCandidateSearchResult(
            lexical_repo_ids=legacy_lexical_repo_ids,
            semantic_repo_ids=semantic_repo_ids,
        )
        legacy_repo_ids = rank_legacy_project_candidate_ids(
            candidate_search.lexical_repo_ids,
            candidate_search.semantic_repo_ids,
        )
        exact_repo_id = query if _EXACT_REPO_QUERY.fullmatch(query) else ""
        if strategy == "v2" and lanes is not None:
            candidate_repo_ids = rank_v2_project_candidate_ids(
                lanes.strict,
                lanes.relaxed,
                candidate_search.semantic_repo_ids,
                exact_repo_id=exact_repo_id,
            )
        else:
            candidate_repo_ids = legacy_repo_ids
        if strategy == "shadow" and lanes is not None:
            from backend.app.services.project_search_shadow import (
                get_project_search_shadow_manager,
            )

            get_project_search_shadow_manager(settings).submit(
                arguments={
                    "query": query,
                    "category": category,
                    "subcategory": subcategory,
                    "language": language,
                    "scope": scope,
                },
                legacy_repo_ids=legacy_repo_ids,
                lanes=lanes,
                semantic_repo_ids=candidate_search.semantic_repo_ids,
                exact_repo_id=exact_repo_id,
            )
        if candidate_repo_ids:
            result = await asyncio.to_thread(
                repository.list_projects,
                source="github",
                scope=scope,
                category=category,
                subcategory=subcategory,
                q="",
                language=language,
                page=page,
                page_size=limit,
                sort="relevance",
                min_stars=min_stars,
                enriched_only=True,
                user_id=None,
                candidate_repo_ids=candidate_repo_ids,
            )
            if bool(getattr(settings, "project_reranker_enabled", False)):
                rerank_limit = max(
                    limit,
                    min(int(settings.project_reranker_candidate_limit), 20),
                )
                rerank_result = await asyncio.to_thread(
                    repository.list_projects,
                    source="github",
                    scope=scope,
                    category=category,
                    subcategory=subcategory,
                    q="",
                    language=language,
                    page=1,
                    page_size=rerank_limit,
                    sort="relevance",
                    min_stars=min_stars,
                    enriched_only=True,
                    user_id=None,
                    candidate_repo_ids=candidate_repo_ids,
                )
                reranker = (
                    reranker_factory()
                    if reranker_factory is not None
                    else get_project_reranker()
                )
                reranked_prefix = await reranker.rerank_repo_ids(
                    _project_reranker_query(query, intent, enriched=client_intent_used),
                    list(rerank_result.get("items") or []),
                )
                reranked_set = set(reranked_prefix)
                ranked_repo_ids = reranked_prefix + [
                    repo_id for repo_id in candidate_repo_ids if repo_id not in reranked_set
                ]
                if ranked_repo_ids:
                    result = await asyncio.to_thread(
                        repository.list_projects,
                        source="github",
                        scope=scope,
                        category=category,
                        subcategory=subcategory,
                        q="",
                        language=language,
                        page=page,
                        page_size=limit,
                        sort="relevance",
                        min_stars=min_stars,
                        enriched_only=True,
                        user_id=None,
                        candidate_repo_ids=ranked_repo_ids,
                    )
        else:
            result = {"items": [], "total": 0}
    else:
        result = await asyncio.to_thread(
            repository.list_projects,
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

    if not hybrid_attempted and mode == "ai" and query and settings.project_semantic_search_enabled:
        try:
            semantic_search = (
                semantic_search_factory()
                if semantic_search_factory is not None
                else get_project_semantic_search()
            )
            semantic_hits = await asyncio.wait_for(
                asyncio.to_thread(semantic_search.search_repo_ids, intent),
                timeout=max(0.1, float(settings.project_semantic_query_timeout_seconds)),
            )
            candidate_repo_ids = [str(hit.repo_id) for hit in semantic_hits if getattr(hit, "repo_id", "")]
            if candidate_repo_ids:
                semantic_result = await asyncio.to_thread(
                    repository.list_projects,
                    source="github",
                    scope=scope,
                    category=category,
                    subcategory=subcategory,
                    q="",
                    language=language,
                    page=page,
                    page_size=limit,
                    sort=effective_sort,
                    min_stars=min_stars,
                    enriched_only=True,
                    user_id=None,
                    candidate_repo_ids=candidate_repo_ids,
                )
                semantic_total = int(semantic_result.get("total") or 0)
                if semantic_total > 0:
                    semantic_items = [
                        public_project_item(item) for item in semantic_result.get("items") or []
                    ]
                    return {
                        **base,
                        "items": semantic_items,
                        "total": semantic_total,
                        "local_total": semantic_total,
                        "has_next": page * limit < semantic_total,
                    }
        except Exception as exc:
            logger.warning("Local project semantic search failed: %s", exc)

    if page != 1:
        return {**base, "fallback_skipped_reason": "fallback_is_first_page_only"}
    if scope != "all":
        return {**base, "fallback_skipped_reason": "scope_requires_local_metrics"}
    if category or subcategory:
        return {**base, "fallback_skipped_reason": "taxonomy_filter_requires_local_classification"}
    if effective_sort not in _FALLBACK_SORTS:
        return {**base, "fallback_skipped_reason": "sort_not_equivalent_on_github_search"}

    fallback_sort = "stars" if effective_sort == "relevance" else effective_sort
    try:
        fallback = await asyncio.to_thread(
            fallback_search,
            q=query,
            category="",
            subcategory="",
            language=language,
            sort=fallback_sort,
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
