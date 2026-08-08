from __future__ import annotations

import asyncio
import logging
import math
from threading import Lock
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.app.core.config import settings

logger = logging.getLogger(__name__)
_ALLOWED_RERANKER_HOSTS = frozenset({"api.siliconflow.cn"})


class ProjectReranker:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(
                max(0.1, float(settings.project_reranker_timeout_seconds)),
            ),
            trust_env=False,
        )
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def rerank_repo_ids(
        self,
        query: str,
        projects: list[dict[str, Any]],
    ) -> list[str]:
        candidates = projects[: max(1, min(int(settings.project_reranker_candidate_limit), 24))]
        fallback = [str(project.get("full_name") or "").strip() for project in candidates]
        fallback = [repo_id for repo_id in fallback if repo_id]
        if not settings.project_reranker_enabled or not settings.siliconflow_api_key:
            return fallback
        if len(fallback) < max(2, int(settings.project_reranker_min_candidates)):
            return fallback
        parsed_url = urlparse(settings.project_reranker_url)
        if parsed_url.scheme != "https" or parsed_url.hostname not in _ALLOWED_RERANKER_HOSTS:
            logger.warning("Project reranker URL is not an approved SiliconFlow endpoint")
            return fallback

        documents = [_project_text(project) for project in candidates]
        try:
            response = await asyncio.wait_for(
                self._client.post(
                    settings.project_reranker_url,
                    headers={
                        "Authorization": f"Bearer {settings.siliconflow_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.project_reranker_model_name,
                        "query": query,
                        "documents": documents,
                        "return_documents": False,
                    },
                ),
                timeout=max(0.1, float(settings.project_reranker_timeout_seconds)),
            )
            response.raise_for_status()
            payload = response.json()
            indices = _validated_indices(payload.get("results"), len(fallback))
        except Exception as exc:
            logger.warning("Project reranker request failed: %s", type(exc).__name__)
            return fallback
        if indices is None:
            return fallback
        return [fallback[index] for index in indices]


def _project_text(project: dict[str, Any], max_chars: int = 1200) -> str:
    values = [
        project.get("full_name"),
        project.get("title"),
        project.get("description"),
        project.get("description_zh"),
        project.get("category_name") or project.get("category_slug"),
        project.get("subcategory_name") or project.get("subcategory_slug"),
        " ".join(str(value) for value in project.get("tags") or []),
        " ".join(str(value) for value in project.get("topics") or []),
        project.get("language"),
    ]
    text = "\n".join(" ".join(str(value or "").split()) for value in values if value)
    return text[:max_chars] or "(empty)"


def _validated_indices(results: Any, candidate_count: int) -> list[int] | None:
    if not isinstance(results, list) or len(results) != candidate_count:
        return None
    ranked: list[tuple[float, int]] = []
    seen: set[int] = set()
    for item in results:
        if not isinstance(item, dict) or isinstance(item.get("index"), bool):
            return None
        try:
            index = int(item["index"])
            score = float(item["relevance_score"])
        except (KeyError, TypeError, ValueError):
            return None
        if index < 0 or index >= candidate_count or index in seen or not math.isfinite(score):
            return None
        seen.add(index)
        ranked.append((score, index))
    ranked.sort(key=lambda value: (-value[0], value[1]))
    return [index for _, index in ranked]


_shared_project_reranker: ProjectReranker | None = None
_shared_project_reranker_lock = Lock()


def get_project_reranker() -> ProjectReranker:
    global _shared_project_reranker
    if _shared_project_reranker is None:
        with _shared_project_reranker_lock:
            if _shared_project_reranker is None:
                _shared_project_reranker = ProjectReranker()
    return _shared_project_reranker
