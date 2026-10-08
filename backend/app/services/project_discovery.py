from __future__ import annotations

import asyncio
import inspect
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from backend.app.core.config import settings
from backend.app.domain.search_semantics import (
    ProjectSearchIntent,
    build_client_project_search_intent,
    build_project_lexical_retrieval_plan,
    build_project_search_intent,
    normalize_search_query,
)
from backend.app.repositories.project_catalog import (
    ProjectLexicalCandidateLanes,
    ProjectLexicalRetrievalPlan,
)
from backend.app.repositories.project_catalog_factory import (
    get_project_catalog_repository,
)
from backend.app.services.ingestion.source_github_mcp import (
    PUBLIC_PROJECT_MIN_STARS,
    search_github_projects_fallback,
)
from backend.app.services.project_reranker import get_project_reranker
from backend.app.services.project_search_ranking import (
    ProjectCandidateSearchResult,
    order_candidates_by_popularity,
    rank_legacy_project_candidate_ids,
    rank_v2_project_candidate_ids,
)
from backend.app.services.project_semantic_search import get_project_semantic_search

logger = logging.getLogger(__name__)

PROJECT_FALLBACK_POLICY = "local_first_github_only_when_semantics_preserved"
PROJECT_SORT_CHOICES = {"relevance", "hot", "stars", "updated", "recent", "name"}
PROJECT_SCOPE_CHOICES = {"all", "today", "recommended"}
_FALLBACK_SORTS = {"relevance", "stars", "updated"}
_EXACT_REPO_QUERY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_EXACT_REPO_NAME_QUERY = re.compile(r"^[A-Za-z0-9_.-]+$")


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
        "description": _clipped(item.get("description"), 320),
        "description_zh": _clipped(item.get("description_zh"), 160),
        "description_en": _clipped(item.get("description_en"), 320),
        "category_slug": _clipped(item.get("category_slug") or item.get("category"), 64),
        "category_name": _clipped(item.get("category_name_zh") or item.get("category_name"), 80),
        "category_name_zh": _clipped(item.get("category_name_zh") or item.get("category_name"), 80),
        "category_name_en": _clipped(item.get("category_name_en"), 80),
        "subcategory_slug": _clipped(item.get("subcategory_slug") or item.get("subcategory"), 64),
        "subcategory_name": _clipped(item.get("subcategory_name_zh") or item.get("subcategory_name"), 80),
        "subcategory_name_zh": _clipped(item.get("subcategory_name_zh") or item.get("subcategory_name"), 80),
        "subcategory_name_en": _clipped(item.get("subcategory_name_en"), 80),
        "tags": _bounded_strings(item.get("tags")),
        "tags_zh": _bounded_strings(item.get("tags_zh")),
        "tags_en": _bounded_strings(item.get("tags_en")),
        "tags_origin": "user" if item.get("tags_origin") == "user" else "system",
        "topics": _bounded_strings(item.get("topics")),
        "language": _clipped(item.get("language"), 64),
        "license": _clipped(item.get("license_spdx_id") or item.get("license"), 64),
        "stars": int(item.get("stars") or 0),
        "forks": int(item.get("forks") or 0),
        "pushed_at": item.get("pushed_at"),
        "daily_star_growth": int(item.get("daily_star_growth") or 0),
        "daily_growth_available": bool(item.get("daily_growth_available")),
        "hot_score": float(item.get("hot_score") or 0),
        "growth_suspicion_score": float(item.get("growth_suspicion_score") or 0),
        "is_recommended": bool(item.get("is_recommended")),
        "result_origin": _clipped(item.get("result_origin") or "aigc_news_local", 40),
    }


def localize_project_item(item: dict[str, Any], lang: str) -> dict[str, Any]:
    """Fold curated English text into the generic slots for English responses.

    The default (zh) payload stays bilingual and Chinese-preferred. With
    ``lang="en"`` the *_en texts are promoted into the generic fields and the
    *_zh fields are omitted, so English-speaking hosts neither quote Chinese
    copy nor pay its token cost.
    """
    if lang != "en":
        return item
    projected = dict(item)
    for generic_key, english_key in (
        ("description", "description_en"),
        ("category_name", "category_name_en"),
        ("subcategory_name", "subcategory_name_en"),
    ):
        english = projected.get(english_key)
        if isinstance(english, str) and english.strip():
            projected[generic_key] = english
    tags_en = projected.get("tags_en")
    if isinstance(tags_en, list) and tags_en:
        projected["tags"] = list(tags_en)
    for zh_key in (
        "description_zh",
        "category_name_zh",
        "subcategory_name_zh",
        "tags_zh",
    ):
        projected.pop(zh_key, None)
    return projected


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


@dataclass(frozen=True, slots=True)
class _ProjectSearchRequest:
    """Normalized search inputs shared by every downstream branch."""

    query: str
    mode: str
    language: str
    category: str
    subcategory: str
    scope: str
    effective_sort: str
    page: int
    limit: int
    min_stars: int
    intent: ProjectSearchIntent
    client_intent_used: bool
    lexical_query: str
    lexical_plan: ProjectLexicalRetrievalPlan


def _normalize_search_request(
    *,
    query: str,
    mode: str,
    language: str,
    client_intent: dict[str, Any] | None,
    category: str,
    subcategory: str,
    scope: str,
    sort: str | None,
    page: int,
    limit: int,
) -> _ProjectSearchRequest:
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
        prefer_relevance=True,
    )
    page = max(1, int(page or 1))
    limit = max(1, min(int(limit or 10), 20))
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
    lexical_plan = build_project_lexical_retrieval_plan(intent)
    return _ProjectSearchRequest(
        query=query,
        mode=mode,
        language=language,
        category=category,
        subcategory=subcategory,
        scope=scope,
        effective_sort=effective_sort,
        page=page,
        limit=limit,
        min_stars=PUBLIC_PROJECT_MIN_STARS,
        intent=intent,
        client_intent_used=client_intent_used,
        lexical_query=lexical_query,
        lexical_plan=lexical_plan,
    )


def _resolve_strategy() -> str:
    strategy = str(getattr(settings, "project_ai_search_strategy", "legacy") or "legacy").strip().lower()
    return strategy if strategy in {"legacy", "shadow", "v2"} else "legacy"


async def _retrieve_hybrid_candidates(
    request: _ProjectSearchRequest,
    repository: Any,
    *,
    use_lanes: bool,
    semantic_search_factory: Any | None,
) -> tuple[ProjectCandidateSearchResult, ProjectLexicalCandidateLanes | None]:
    """Run lexical and semantic retrieval concurrently; a failing source degrades to empty."""
    lexical_search = _declared_callable(
        repository,
        "find_lexical_candidate_lanes" if use_lanes else "find_lexical_candidate_repo_ids",
    )
    lexical_task = asyncio.to_thread(
        lexical_search,
        q=request.lexical_plan if use_lanes else request.lexical_query,
        scope=request.scope,
        category=request.category,
        subcategory=request.subcategory,
        language=request.language,
        min_stars=request.min_stars,
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
            asyncio.to_thread(semantic_search.search_repo_ids, request.intent),
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
    return (
        ProjectCandidateSearchResult(
            lexical_repo_ids=legacy_lexical_repo_ids,
            semantic_repo_ids=semantic_repo_ids,
        ),
        lanes,
    )


def _candidate_id_pool(
    lanes: ProjectLexicalCandidateLanes,
    semantic_repo_ids: tuple[str, ...],
) -> list[str]:
    return list(
        dict.fromkeys(
            [candidate.repo_id for candidate in lanes.strict]
            + [candidate.repo_id for candidate in lanes.relaxed]
            + list(semantic_repo_ids)
        )
    )


async def _lookup_adoption_stars(
    repository: Any,
    lanes: ProjectLexicalCandidateLanes,
    semantic_repo_ids: tuple[str, ...],
    *,
    needed: bool,
) -> dict[str, int]:
    stars_lookup = _declared_callable(repository, "get_project_stars_map")
    if not needed or not callable(stars_lookup):
        return {}
    try:
        return await asyncio.to_thread(
            stars_lookup, _candidate_id_pool(lanes, semantic_repo_ids)
        )
    except Exception:
        logger.warning(
            "project search adoption stars lookup failed; falling back to fit-only ranking",
            exc_info=True,
        )
        return {}


async def _lookup_project_popularity(
    repository: Any,
    lanes: ProjectLexicalCandidateLanes,
    semantic_repo_ids: tuple[str, ...],
    *,
    needed: bool,
) -> dict[str, tuple[int, int]]:
    popularity_lookup = _declared_callable(repository, "get_project_popularity_map")
    if not needed or not callable(popularity_lookup):
        return {}
    try:
        return await asyncio.to_thread(
            popularity_lookup, _candidate_id_pool(lanes, semantic_repo_ids)
        )
    except Exception:
        logger.warning(
            "project search popularity lookup failed; falling back to fit-only ranking",
            exc_info=True,
        )
        return {}


async def _rank_hybrid_candidates(
    repository: Any,
    *,
    strategy: str,
    lanes: ProjectLexicalCandidateLanes | None,
    candidate_search: ProjectCandidateSearchResult,
    exact_repo_id: str,
    client_intent_used: bool = False,
) -> tuple[list[str], list[str]]:
    """Return (ranked candidate ids, legacy ranked ids); legacy stays authoritative outside v2."""
    legacy_repo_ids = rank_legacy_project_candidate_ids(
        candidate_search.lexical_repo_ids,
        candidate_search.semantic_repo_ids,
    )
    if strategy != "v2" or lanes is None:
        return legacy_repo_ids, legacy_repo_ids
    adoption_weight = float(
        getattr(settings, "project_search_adoption_weight", 0.0) or 0.0
    )
    # 语义 lane 实际产出候选时，展示序默认在相关性之上叠加长期热度（近
    # 7 日星增 + 总星数，相关性占 2/3，精确命中仍钉榜首）；lane 为空（语义
    # 关闭或检索失败）保持 lane 融合拟合序，优雅降级。
    # 例外一：宿主 agent 传入结构化 intent 的是任务型复用检索，要的是任务
    # 适配而非人气——此时保持 v2 拟合序。
    # 全概念匹配始终先于部分匹配；不能用页大小决定相关性，否则翻页或
    # 改 limit 就会把热门但偏题的候选抬到前面。
    heat_first = (
        bool(candidate_search.semantic_repo_ids)
        and bool(getattr(settings, "project_semantic_heat_first", True))
        and not client_intent_used
    )
    adoption_stars = await _lookup_adoption_stars(
        repository,
        lanes,
        candidate_search.semantic_repo_ids,
        needed=adoption_weight > 0,
    )
    popularity_map = await _lookup_project_popularity(
        repository,
        lanes,
        candidate_search.semantic_repo_ids,
        needed=heat_first,
    )
    ranked_repo_ids = rank_v2_project_candidate_ids(
        lanes.strict,
        lanes.relaxed,
        candidate_search.semantic_repo_ids,
        exact_repo_id=exact_repo_id,
        adoption_stars=adoption_stars,
        adoption_weight=adoption_weight,
    )
    if heat_first and popularity_map:
        ranked_repo_ids = order_candidates_by_popularity(
            ranked_repo_ids,
            popularity_map,
            exact_repo_id=exact_repo_id,
            pinned_repo_ids=tuple(candidate.repo_id for candidate in lanes.strict),
        )
    return ranked_repo_ids, legacy_repo_ids


def _submit_shadow_comparison(
    request: _ProjectSearchRequest,
    *,
    lexical_lane_search: Any,
    shadow_manager_factory: Any | None,
    legacy_repo_ids: list[str],
    semantic_repo_ids: tuple[str, ...],
    exact_repo_id: str,
) -> None:
    """Fire-and-forget lane comparison against the legacy ordering (shadow strategy)."""
    if shadow_manager_factory is None:
        from backend.app.services.project_search_shadow import (
            get_project_search_shadow_manager,
        )

        def shadow_manager_factory() -> Any:
            return get_project_search_shadow_manager(settings)

    lane_arguments = {
        "q": request.lexical_plan,
        "scope": request.scope,
        "category": request.category,
        "subcategory": request.subcategory,
        "language": request.language,
        "min_stars": request.min_stars,
        "enriched_only": True,
        "strict_limit": 150,
        "relaxed_limit": 150,
    }
    shadow_manager_factory().submit(
        arguments={
            "query": request.query,
            "category": request.category,
            "subcategory": request.subcategory,
            "language": request.language,
            "scope": request.scope,
            "strict_term_count": len(request.lexical_plan.strict_terms),
            "concept_count": len(request.lexical_plan.concepts),
        },
        legacy_repo_ids=legacy_repo_ids,
        lanes_call=lambda: lexical_lane_search(**lane_arguments),
        semantic_repo_ids=semantic_repo_ids,
        exact_repo_id=exact_repo_id,
    )


async def _list_candidate_page(
    repository: Any,
    request: _ProjectSearchRequest,
    *,
    page: int,
    page_size: int,
    candidate_repo_ids: list[str],
) -> dict[str, Any]:
    """Hydrate one relevance-ordered page from the candidate id ordering."""
    return await asyncio.to_thread(
        repository.list_projects,
        source="github",
        scope=request.scope,
        category=request.category,
        subcategory=request.subcategory,
        q="",
        language=request.language,
        page=page,
        page_size=page_size,
        sort="relevance",
        min_stars=request.min_stars,
        enriched_only=True,
        user_id=None,
        candidate_repo_ids=candidate_repo_ids,
    )


async def _apply_reranker(
    repository: Any,
    request: _ProjectSearchRequest,
    *,
    candidate_repo_ids: list[str],
    reranker_factory: Any | None,
) -> dict[str, Any]:
    """Optionally re-order the hydrated prefix with the reranker, keeping the tail order."""
    result = await _list_candidate_page(
        repository,
        request,
        page=request.page,
        page_size=request.limit,
        candidate_repo_ids=candidate_repo_ids,
    )
    if not bool(getattr(settings, "project_reranker_enabled", False)):
        return result
    rerank_limit = max(
        request.limit,
        min(int(settings.project_reranker_candidate_limit), 20),
    )
    rerank_result = await _list_candidate_page(
        repository,
        request,
        page=1,
        page_size=rerank_limit,
        candidate_repo_ids=candidate_repo_ids,
    )
    reranker = (
        reranker_factory()
        if reranker_factory is not None
        else get_project_reranker()
    )
    reranked_prefix = await reranker.rerank_repo_ids(
        _project_reranker_query(request.query, request.intent, enriched=request.client_intent_used),
        list(rerank_result.get("items") or []),
    )
    reranked_set = set(reranked_prefix)
    ranked_repo_ids = reranked_prefix + [
        repo_id for repo_id in candidate_repo_ids if repo_id not in reranked_set
    ]
    if not ranked_repo_ids:
        return result
    return await _list_candidate_page(
        repository,
        request,
        page=request.page,
        page_size=request.limit,
        candidate_repo_ids=ranked_repo_ids,
    )


async def _resolve_unique_repo_name_exact(repository: Any, query: str) -> str:
    """裸仓库名查询的钉顶解析：名段唯一命中一个 active 项目时返回其 repo_id。

    多个命中（歧义）、零命中、仓库不支持该查询或查询失败时都返回 ""，
    退化为普通相关性排序——宁可不钉，也不错钉。
    """
    lookup = _declared_callable(repository, "find_repo_ids_by_name_segment")
    if lookup is None:
        return ""
    try:
        raw_repo_ids = await asyncio.to_thread(lookup, name=query, limit=2)
    except Exception as exc:
        logger.warning("Repo-name exact pin lookup failed for %r: %s", query, exc)
        return ""
    repo_ids = [
        repo_id
        for repo_id in (str(value or "").strip() for value in raw_repo_ids)
        if repo_id
    ]
    return repo_ids[0] if len(repo_ids) == 1 else ""


async def _hybrid_search(
    request: _ProjectSearchRequest,
    repository: Any,
    *,
    strategy: str,
    semantic_search_factory: Any | None,
    reranker_factory: Any | None,
    shadow_manager_factory: Any | None,
) -> tuple[dict[str, Any], bool]:
    """Relevance pipeline: candidate retrieval → strategy ranking → shadow → hydration.

    Returns (page result, strict_lexical_empty): the flag is True when no local
    repo matched all query terms lexically (v2: empty strict lane; legacy: empty
    flat lexical candidates), i.e. the ranked pool rests on relaxed/semantic
    matches only.
    """
    lexical_lane_search = _declared_callable(repository, "find_lexical_candidate_lanes")
    use_lanes = strategy == "v2" and callable(lexical_lane_search)
    candidate_search, lanes = await _retrieve_hybrid_candidates(
        request,
        repository,
        use_lanes=use_lanes,
        semantic_search_factory=semantic_search_factory,
    )
    strict_lexical_empty = not candidate_search.lexical_repo_ids
    exact_repo_id = request.query if _EXACT_REPO_QUERY.fullmatch(request.query) else ""
    if strategy == "v2" and not exact_repo_id and _EXACT_REPO_NAME_QUERY.fullmatch(request.query):
        # 裸仓库名（如 "pi"）：名段唯一命中时视同精确查询钉顶，v2/heat
        # 展示序下不被热度罢黜；legacy 序由 SQL 名段层级自然置顶，无需查询。
        exact_repo_id = await _resolve_unique_repo_name_exact(repository, request.query)
    candidate_repo_ids, legacy_repo_ids = await _rank_hybrid_candidates(
        repository,
        strategy=strategy,
        lanes=lanes,
        candidate_search=candidate_search,
        exact_repo_id=exact_repo_id,
        client_intent_used=request.client_intent_used,
    )
    if strategy == "shadow" and callable(lexical_lane_search):
        _submit_shadow_comparison(
            request,
            lexical_lane_search=lexical_lane_search,
            shadow_manager_factory=shadow_manager_factory,
            legacy_repo_ids=legacy_repo_ids,
            semantic_repo_ids=candidate_search.semantic_repo_ids,
            exact_repo_id=exact_repo_id,
        )
    if not candidate_repo_ids:
        return {"items": [], "total": 0}, strict_lexical_empty
    result = await _apply_reranker(
        repository,
        request,
        candidate_repo_ids=candidate_repo_ids,
        reranker_factory=reranker_factory,
    )
    return result, strict_lexical_empty


async def _list_plain_page(repository: Any, request: _ProjectSearchRequest) -> dict[str, Any]:
    """Non-relevance path: the catalog executes keyword filtering and sorting directly."""
    return await asyncio.to_thread(
        repository.list_projects,
        source="github",
        scope=request.scope,
        category=request.category,
        subcategory=request.subcategory,
        q=request.query,
        language=request.language,
        page=request.page,
        page_size=request.limit,
        sort=request.effective_sort,
        min_stars=request.min_stars,
        enriched_only=True,
        user_id=None,
    )


def _assemble_base_response(request: _ProjectSearchRequest, result: dict[str, Any]) -> dict[str, Any]:
    items = [public_project_item(item) for item in result.get("items") or []]
    total = int(result.get("total") or 0)
    return {
        "items": items,
        "total": total,
        "page": request.page,
        "page_size": request.limit,
        "has_next": request.page * request.limit < total,
        "min_stars": request.min_stars,
        "scope": request.scope,
        "category": request.category,
        "subcategory": request.subcategory,
        "language": request.language,
        "q": request.query,
        "sort": request.effective_sort,
        "source": "github",
        "search_mode": request.mode,
        "result_origin": "aigc_news_local",
        "local_total": total,
        "fallback_used": False,
        "fallback_reason": "",
        "fallback_skipped_reason": "",
        "fallback_policy": PROJECT_FALLBACK_POLICY,
    }


async def _semantic_zero_result_retry(
    repository: Any,
    request: _ProjectSearchRequest,
    base: dict[str, Any],
    *,
    semantic_search_factory: Any | None,
) -> dict[str, Any] | None:
    """Local semantic retry after an empty SQL result; returns the updated response or None."""
    if not settings.project_semantic_search_enabled:
        return None
    try:
        semantic_search = (
            semantic_search_factory()
            if semantic_search_factory is not None
            else get_project_semantic_search()
        )
        semantic_hits = await asyncio.wait_for(
            asyncio.to_thread(semantic_search.search_repo_ids, request.intent),
            timeout=max(0.1, float(settings.project_semantic_query_timeout_seconds)),
        )
        candidate_repo_ids = [str(hit.repo_id) for hit in semantic_hits if getattr(hit, "repo_id", "")]
        if not candidate_repo_ids:
            return None
        semantic_result = await asyncio.to_thread(
            repository.list_projects,
            source="github",
            scope=request.scope,
            category=request.category,
            subcategory=request.subcategory,
            q="",
            language=request.language,
            page=request.page,
            page_size=request.limit,
            sort=request.effective_sort,
            min_stars=request.min_stars,
            enriched_only=True,
            user_id=None,
            candidate_repo_ids=candidate_repo_ids,
        )
        semantic_total = int(semantic_result.get("total") or 0)
        if semantic_total <= 0:
            return None
        semantic_items = [
            public_project_item(item) for item in semantic_result.get("items") or []
        ]
        return {
            **base,
            "items": semantic_items,
            "total": semantic_total,
            "local_total": semantic_total,
            "has_next": request.page * request.limit < semantic_total,
        }
    except Exception as exc:
        logger.warning("Local project semantic search failed: %s", exc)
        return None


def _github_fallback_skip_reason(request: _ProjectSearchRequest) -> str:
    """Gates that would make a GitHub API fallback lossy; checked in priority order."""
    if request.page != 1:
        return "fallback_is_first_page_only"
    if request.scope != "all":
        return "scope_requires_local_metrics"
    if request.category or request.subcategory:
        return "taxonomy_filter_requires_local_classification"
    if request.effective_sort not in _FALLBACK_SORTS:
        return "sort_not_equivalent_on_github_search"
    return ""


async def _run_github_fallback(
    request: _ProjectSearchRequest,
    base: dict[str, Any],
    *,
    fallback_search: Any,
    reason: str = "local_zero_results",
) -> dict[str, Any]:
    fallback_sort = "stars" if request.effective_sort == "relevance" else request.effective_sort
    try:
        fallback = await asyncio.to_thread(
            fallback_search,
            q=request.query,
            category="",
            subcategory="",
            language=request.language,
            sort=fallback_sort,
            limit=request.limit,
            min_stars=request.min_stars,
            mode=request.mode,
        )
    except Exception as exc:
        logger.warning("GitHub project fallback failed: %s", exc)
        return {
            **base,
            "fallback_used": True,
            "fallback_reason": reason,
            "fallback_error": f"GitHub fallback failed: {exc}",
        }

    fallback_items = [public_project_item(item) for item in fallback.get("items") or []]
    result = {
        **base,
        "items": fallback_items,
        "total": len(fallback_items),
        "has_next": False,
        "result_origin": "github_api_fallback" if fallback_items else "aigc_news_local",
        "fallback_used": True,
        "fallback_reason": reason,
        "fallback_error": str(fallback.get("error") or ""),
        "github_total_count": int(fallback.get("github_total_count") or 0),
        "fallback_queries": fallback.get("queries") or [],
        "fallback_cache_hit": bool(fallback.get("cache_hit")),
    }
    if fallback.get("error"):
        for key in ("items", "total", "has_next", "result_origin"):
            result[key] = base[key]
    return result


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
    shadow_manager_factory: Any | None = None,
) -> dict[str, Any]:
    request = _normalize_search_request(
        query=query,
        mode=mode,
        language=language,
        client_intent=client_intent,
        category=category,
        subcategory=subcategory,
        scope=scope,
        sort=sort,
        page=page,
        limit=limit,
    )
    repository = (
        repository_factory()
        if repository_factory is not None
        else get_project_catalog_repository()
    )
    strategy = _resolve_strategy()
    lexical_candidate_search = _declared_callable(
        repository,
        "find_lexical_candidate_repo_ids",
    )
    hybrid_attempted = bool(
        request.query
        and request.effective_sort == "relevance"
        and callable(lexical_candidate_search)
    )
    strict_lexical_empty = False
    if hybrid_attempted:
        result, strict_lexical_empty = await _hybrid_search(
            request,
            repository,
            strategy=strategy,
            semantic_search_factory=semantic_search_factory,
            reranker_factory=reranker_factory,
            shadow_manager_factory=shadow_manager_factory,
        )
    else:
        result = await _list_plain_page(repository, request)
    base = _assemble_base_response(request, result)
    skip_reason = _github_fallback_skip_reason(request)
    # generic 低相关护栏：strict 词法 lane 全空 = 本地精选库没有任何项目
    # 同时命中全部查询词，残留结果只是宽松/语义 lane 的热度噪声（典型如
    # "windows screenshot tool" 命中无关 AI 项目）。此时把结果让给 GitHub
    # 全量语料，而不是返回噪声。ai 模式不受影响：精选库语义命中在其域内
    # 通常有意义。
    if (
        base["total"] > 0
        and strict_lexical_empty
        and request.mode == "generic"
        and not skip_reason
    ):
        return await _run_github_fallback(
            request,
            base,
            fallback_search=fallback_search,
            reason="local_low_relevance",
        )
    if base["total"] > 0:
        return base

    if not hybrid_attempted and request.query:
        retried = await _semantic_zero_result_retry(
            repository,
            request,
            base,
            semantic_search_factory=semantic_search_factory,
        )
        if retried is not None:
            return retried

    if skip_reason:
        return {**base, "fallback_skipped_reason": skip_reason}
    return await _run_github_fallback(request, base, fallback_search=fallback_search)
