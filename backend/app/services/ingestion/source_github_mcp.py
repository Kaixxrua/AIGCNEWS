from __future__ import annotations

import logging
from collections import OrderedDict
from copy import deepcopy
from threading import Lock
from time import monotonic
from typing import Any, Dict, List, Literal

import httpx

from backend.app.core.config import settings
from backend.app.services.ingestion.source_github import GITHUB_API_BASE, _build_headers
from backend.app.services.search_semantics import normalize_search_query, project_search_terms

logger = logging.getLogger(__name__)

_AI_TERMS = ("AI", "LLM", "RAG", "agent", "generative-ai", "mcp", "workflow")
_CATEGORY_TERMS = {
    "rag_knowledge": ("RAG", "knowledge-base", "retrieval-augmented-generation"),
    "agents_automation": ("agent", "mcp", "workflow", "automation"),
    "coding_tools": ("coding", "developer-tools", "code-generation"),
    "ai_apps": ("AI", "chatbot", "web-ui"),
    "models_infra": ("LLM", "model", "inference"),
    "multimodal_tools": ("multimodal", "vision", "image", "audio"),
    "data_eval_training": ("evaluation", "dataset", "training"),
}
_SORT_MAP = {
    "hot": "stars",
    "stars": "stars",
    "updated": "updated",
    "recent": "updated",
    "name": "stars",
}
_SEARCH_MODES = {"generic", "ai"}
PUBLIC_PROJECT_MIN_STARS = 500
_CACHE_MAX_ENTRIES = 128
_CACHE_SUCCESS_TTL_SECONDS = 300.0
_CACHE_EMPTY_TTL_SECONDS = 45.0
_FALLBACK_CACHE: OrderedDict[tuple[Any, ...], tuple[float, Dict[str, Any]]] = OrderedDict()
_FALLBACK_CACHE_LOCK = Lock()


def _clean_query_words(value: str, *, max_words: int = 8) -> List[str]:
    return project_search_terms(value, max_terms=max_words)


def _build_queries(
    *,
    q: str,
    category: str,
    subcategory: str,
    language: str,
    min_stars: int,
    mode: Literal["generic", "ai"] = "ai",
) -> List[str]:
    if mode not in _SEARCH_MODES:
        raise ValueError(f"Unsupported GitHub search mode: {mode}")

    base_parts = _clean_query_words(q)
    if mode == "ai":
        taxonomy_terms = list(_CATEGORY_TERMS.get(category, ())) + _clean_query_words(subcategory, max_words=3)
        if taxonomy_terms:
            base_parts.extend(term for term in taxonomy_terms if term not in base_parts)

    qualifiers = [f"stars:>={max(0, int(min_stars or 0))}"]
    if language:
        qualifiers.append(f"language:{language.strip()}")

    if mode == "generic":
        if not base_parts:
            return []
        # GitHub combines free-text terms with AND semantics. Start with the
        # caller's exact intent, then progressively relax long feature lists so
        # an analogy/product name (for example "like iShot") cannot turn a
        # useful software search into a guaranteed zero-result query.
        term_sets = [base_parts]
        if len(base_parts) > 4:
            term_sets.append(base_parts[:4])
        if len(base_parts) > 2:
            term_sets.append(base_parts[:2])
        return list(
            dict.fromkeys(
                " ".join(terms + qualifiers)
                for terms in term_sets
                if terms
            )
        )

    queries: List[str] = []
    primary_terms = base_parts or list(_AI_TERMS[:3])
    queries.append(" ".join(primary_terms + qualifiers))

    # Add an AI-constrained retry so specific AI requests still get a chance to
    # match GitHub search syntax without affecting generic software discovery.
    ai_terms = [term for term in _AI_TERMS if term not in primary_terms]
    queries.append(" ".join((base_parts[:4] + ai_terms[:3] + qualifiers) if base_parts else list(_AI_TERMS[:5]) + qualifiers))

    deduped: List[str] = []
    for query in queries:
        normalized = " ".join(query.split())
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def _has_eligible_stars(item: Dict[str, Any], *, min_stars: int) -> bool:
    stars = item.get("stargazers_count")
    return isinstance(stars, int) and not isinstance(stars, bool) and stars >= min_stars


def _normalize_repo(item: Dict[str, Any]) -> Dict[str, Any]:
    full_name = str(item.get("full_name") or item.get("name") or "").strip()
    topics = item.get("topics") if isinstance(item.get("topics"), list) else []
    language = str(item.get("language") or "").strip()
    tags = ([language] if language else []) + [str(topic) for topic in topics[:8]]
    return {
        "id": f"github-direct:{full_name or item.get('id', '')}",
        "source": "github",
        "result_origin": "github_api_fallback",
        "repo_id": item.get("id") or item.get("node_id") or full_name,
        "website_id": None,
        "full_name": full_name,
        "title": full_name,
        "url": item.get("html_url") or "",
        "domain": None,
        "image_url": None,
        "description": item.get("description") or "",
        "description_zh": "",
        "category_slug": "",
        "category_name": "",
        "subcategory_slug": "",
        "subcategory_name": "",
        "tags": tags,
        "language": language,
        "topics": topics[:12],
        "stars": int(item.get("stargazers_count") or 0),
        "forks": int(item.get("forks_count") or 0),
        "watchers": int(item.get("watchers_count") or 0),
        "open_issues": int(item.get("open_issues_count") or 0),
        "created_at": item.get("created_at") or None,
        "pushed_at": item.get("pushed_at") or None,
        "first_seen_at": None,
        "last_seen_at": None,
        "last_snapshot_at": None,
        "snapshot_date": None,
        "rank_in_period": None,
        "raw_score": int(item.get("stargazers_count") or 0),
        "score": int(item.get("stargazers_count") or 0),
        "confidence": 0,
    }


def _search_once(client: httpx.Client, query: str, *, limit: int, sort: str, use_token: bool) -> Dict[str, Any]:
    params = {
        "q": query,
        "sort": _SORT_MAP.get(sort, "stars"),
        "order": "desc",
        "per_page": min(max(1, limit), 20),
        "page": 1,
    }
    response = client.get(
        f"{GITHUB_API_BASE}/search/repositories",
        headers=_build_headers(use_token=use_token),
        params=params,
    )
    if response.status_code == 401 and use_token:
        logger.warning("[MCP][GitHubFallback] token 401; retrying anonymously")
        return _search_once(client, query, limit=limit, sort=sort, use_token=False)
    if response.status_code in {403, 429}:
        return {"items": [], "total_count": 0, "error": f"GitHub API rate limited or forbidden: HTTP {response.status_code}"}
    try:
        response.raise_for_status()
    except Exception as exc:
        return {"items": [], "total_count": 0, "error": f"GitHub API HTTP {response.status_code}: {exc}"}
    data = response.json()
    return {
        "items": data.get("items") if isinstance(data.get("items"), list) else [],
        "total_count": int(data.get("total_count") or 0),
        "error": "",
    }


def _fallback_cache_key(
    *,
    mode: str,
    q: str,
    category: str,
    subcategory: str,
    language: str,
    sort: str,
    limit: int,
    min_stars: int,
) -> tuple[Any, ...]:
    return (
        mode,
        normalize_search_query(q).casefold(),
        (category or "").lower().strip(),
        (subcategory or "").lower().strip(),
        (language or "").lower().strip(),
        (sort or "stars").lower().strip(),
        limit,
        min_stars,
        bool(settings.mcp_github_fallback_use_token),
    )


def _get_cached_fallback(key: tuple[Any, ...]) -> Dict[str, Any] | None:
    now = monotonic()
    with _FALLBACK_CACHE_LOCK:
        cached = _FALLBACK_CACHE.get(key)
        if cached is None:
            return None
        expires_at, result = cached
        if expires_at <= now:
            _FALLBACK_CACHE.pop(key, None)
            return None
        _FALLBACK_CACHE.move_to_end(key)
        return deepcopy(result)


def _set_cached_fallback(key: tuple[Any, ...], result: Dict[str, Any]) -> None:
    ttl = _CACHE_SUCCESS_TTL_SECONDS if result.get("items") else _CACHE_EMPTY_TTL_SECONDS
    with _FALLBACK_CACHE_LOCK:
        _FALLBACK_CACHE[key] = (monotonic() + ttl, deepcopy(result))
        _FALLBACK_CACHE.move_to_end(key)
        while len(_FALLBACK_CACHE) > _CACHE_MAX_ENTRIES:
            _FALLBACK_CACHE.popitem(last=False)


def _clear_fallback_cache() -> None:
    with _FALLBACK_CACHE_LOCK:
        _FALLBACK_CACHE.clear()


def search_github_projects_fallback(
    *,
    q: str = "",
    category: str = "",
    subcategory: str = "",
    language: str = "",
    sort: str = "stars",
    limit: int = 10,
    min_stars: int = PUBLIC_PROJECT_MIN_STARS,
    mode: Literal["generic", "ai"] = "generic",
) -> Dict[str, Any]:
    """Run a bounded, read-only GitHub Search after local project search misses."""

    if mode not in _SEARCH_MODES:
        raise ValueError(f"Unsupported GitHub search mode: {mode}")
    if not settings.mcp_github_fallback_enabled:
        return {"items": [], "total": 0, "github_total_count": 0, "queries": [], "error": "GitHub fallback is disabled."}

    limit = max(1, min(int(limit or 10), 20))
    min_stars = max(PUBLIC_PROJECT_MIN_STARS, int(min_stars or 0))
    cache_key = _fallback_cache_key(
        mode=mode,
        q=q,
        category=category,
        subcategory=subcategory,
        language=language,
        sort=sort,
        limit=limit,
        min_stars=min_stars,
    )
    cached = _get_cached_fallback(cache_key)
    if cached is not None:
        cached["cache_hit"] = True
        return cached

    queries = _build_queries(
        q=q,
        category=category,
        subcategory=subcategory,
        language=language,
        min_stars=min_stars,
        mode=mode,
    )
    if not queries:
        result = {
            "items": [],
            "total": 0,
            "github_total_count": 0,
            "queries": [],
            "error": "A concise GitHub search query is required for generic project discovery.",
            "cache_hit": False,
        }
        _set_cached_fallback(cache_key, result)
        return result

    seen: set[str] = set()
    repos: List[Dict[str, Any]] = []
    github_total_count = 0
    errors: List[str] = []

    timeout = httpx.Timeout(
        connect=min(float(settings.mcp_github_fallback_timeout_seconds or 8.0), 8.0),
        read=float(settings.mcp_github_fallback_timeout_seconds or 8.0),
        write=5.0,
        pool=5.0,
    )
    with httpx.Client(timeout=timeout, trust_env=True, follow_redirects=True) as client:
        for query in queries:
            result = _search_once(
                client,
                query,
                limit=limit,
                sort=sort,
                use_token=bool(settings.mcp_github_fallback_use_token),
            )
            github_total_count = max(github_total_count, int(result.get("total_count") or 0))
            if result.get("error"):
                errors.append(str(result["error"]))
            for item in result.get("items") or []:
                if not isinstance(item, dict) or not _has_eligible_stars(
                    item,
                    min_stars=min_stars,
                ):
                    continue
                normalized = _normalize_repo(item)
                key = str(normalized.get("full_name") or normalized.get("repo_id") or "").casefold()
                if not key or key in seen:
                    continue
                seen.add(key)
                repos.append(normalized)

    repos = [
        repo
        for repo in repos
        if isinstance(repo.get("stars"), int)
        and not isinstance(repo.get("stars"), bool)
        and int(repo["stars"]) >= min_stars
    ]

    if sort == "updated":
        repos.sort(key=lambda item: str(item.get("full_name") or "").casefold())
        repos.sort(
            key=lambda item: (
                str(item.get("pushed_at") or ""),
                int(item.get("stars") or 0),
            ),
            reverse=True,
        )
    else:
        repos.sort(
            key=lambda item: (
                -int(item.get("stars") or 0),
                -int(item.get("forks") or 0),
                str(item.get("full_name") or "").casefold(),
            )
        )

    final = {
        "items": repos[:limit],
        "total": len(repos[:limit]),
        "github_total_count": github_total_count,
        "queries": queries,
        "error": "; ".join(dict.fromkeys(errors)) if errors and not repos else "",
        "cache_hit": False,
    }
    _set_cached_fallback(cache_key, final)
    return deepcopy(final)


def search_github_ai_projects_fallback(
    *,
    q: str = "",
    category: str = "",
    subcategory: str = "",
    language: str = "",
    sort: str = "stars",
    limit: int = 10,
    min_stars: int = PUBLIC_PROJECT_MIN_STARS,
) -> Dict[str, Any]:
    """Compatibility wrapper for the curated AI-project fallback behavior."""

    return search_github_projects_fallback(
        q=q,
        category=category,
        subcategory=subcategory,
        language=language,
        sort=sort,
        limit=limit,
        min_stars=min_stars,
        mode="ai",
    )
