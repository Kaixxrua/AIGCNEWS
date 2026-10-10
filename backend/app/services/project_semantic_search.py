from __future__ import annotations

import logging
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Any

from backend.app.core.config import settings
from backend.app.domain.search_semantics import (
    ProjectSearchIntent,
    build_project_search_intent,
)
from backend.app.repositories.project_vector_repo import ProjectVectorRepository

logger = logging.getLogger(__name__)
_WARMUP_QUERIES = (
    "AI developer tools and open source projects",
    "AI 编程助手",
    "知识库问答",
    "自托管书签管理",
)
_RECENT_WARMUP_VECTOR_LIMIT = 8


@dataclass(frozen=True)
class ProjectSemanticHit:
    repo_id: str
    score: float


def reciprocal_rank_fusion(
    rankings: list[list[ProjectSemanticHit]],
    *,
    rank_constant: int = 60,
    limit: int,
) -> list[ProjectSemanticHit]:
    scores: dict[str, float] = {}
    best_ranks: dict[str, int] = {}
    for ranking in rankings:
        seen: set[str] = set()
        for rank, hit in enumerate(ranking, start=1):
            if not hit.repo_id or hit.repo_id in seen:
                continue
            seen.add(hit.repo_id)
            scores[hit.repo_id] = scores.get(hit.repo_id, 0.0) + 1.0 / (rank_constant + rank)
            best_ranks[hit.repo_id] = min(best_ranks.get(hit.repo_id, rank), rank)
    ordered = sorted(scores, key=lambda repo_id: (-scores[repo_id], best_ranks[repo_id], repo_id))
    return [ProjectSemanticHit(repo_id=repo_id, score=scores[repo_id]) for repo_id in ordered[:limit]]


class ProjectSemanticSearch:
    def __init__(
        self,
        *,
        vectors: ProjectVectorRepository | None = None,
        embeddings: Any = None,
    ) -> None:
        self.vectors = vectors or ProjectVectorRepository()
        self._embeddings = embeddings
        self._embedding_lock = Lock()
        self._warmup_lock = Lock()
        self._warmup_vectors: dict[str, tuple[float, ...]] = {}
        self._recent_vectors: OrderedDict[str, tuple[float, ...]] = OrderedDict()
        self._recent_vectors_lock = Lock()

    def _get_embeddings(self):
        if self._embeddings is None:
            with self._embedding_lock:
                if self._embeddings is None:
                    from backend.app.core.model_factory import get_embedding_model

                    self._embeddings = get_embedding_model()
        return self._embeddings

    def search_repo_ids(
        self,
        query: str | ProjectSearchIntent,
    ) -> list[ProjectSemanticHit]:
        if not settings.project_semantic_search_enabled:
            return []
        intent = query if isinstance(query, ProjectSearchIntent) else build_project_search_intent(query)
        if not intent.semantic_queries:
            return []
        rankings: list[list[ProjectSemanticHit]] = []
        embeddings = self._get_embeddings()
        for semantic_query in intent.semantic_queries:
            vector = list(embeddings.embed_query(semantic_query))
            hits = self.vectors.search_repo_ids(
                vector,
                chunk_limit=settings.project_semantic_chunk_limit,
                repo_limit=settings.project_semantic_repo_limit,
                min_score=settings.project_semantic_min_score,
            )
            with self._recent_vectors_lock:
                self._recent_vectors[semantic_query] = tuple(vector)
                self._recent_vectors.move_to_end(semantic_query)
                while len(self._recent_vectors) > _RECENT_WARMUP_VECTOR_LIMIT:
                    self._recent_vectors.popitem(last=False)
            rankings.append([ProjectSemanticHit(repo_id=hit.repo_id, score=hit.score) for hit in hits])
        if len(rankings) == 1:
            return rankings[0]
        return reciprocal_rank_fusion(
            rankings,
            limit=settings.project_semantic_repo_limit,
        )

    def warmup(self) -> None:
        # Keep representative and recently used index paths warm at real search
        # depth. Periodic runs reuse vectors instead of billing embedding again.
        with self._warmup_lock:
            for query in _WARMUP_QUERIES:
                for variant in build_project_search_intent(query).semantic_queries:
                    if variant not in self._warmup_vectors:
                        self._warmup_vectors[variant] = tuple(
                            self._get_embeddings().embed_query(variant)
                        )
            with self._recent_vectors_lock:
                vectors = {**self._warmup_vectors, **self._recent_vectors}
            for vector in vectors.values():
                self.vectors.search_repo_ids(
                    list(vector),
                    chunk_limit=settings.project_semantic_chunk_limit,
                    repo_limit=settings.project_semantic_repo_limit,
                    min_score=settings.project_semantic_min_score,
                )

    def close(self) -> None:
        self.vectors.close()


_shared_project_semantic_search: ProjectSemanticSearch | None = None
_shared_search_lock = Lock()
_warmup_lock = Lock()


def get_project_semantic_search() -> ProjectSemanticSearch:
    global _shared_project_semantic_search
    if _shared_project_semantic_search is None:
        with _shared_search_lock:
            if _shared_project_semantic_search is None:
                _shared_project_semantic_search = ProjectSemanticSearch()
    return _shared_project_semantic_search


def warmup_project_semantic_search() -> dict[str, Any]:
    if not settings.project_semantic_search_enabled:
        return {"status": "disabled"}
    if not _warmup_lock.acquire(blocking=False):
        return {"status": "already_running"}
    try:
        get_project_semantic_search().warmup()
        return {"status": "success"}
    except Exception as exc:
        logger.warning("Project semantic search warmup failed: %s", exc)
        return {"status": "failed", "error": str(exc)}
    finally:
        _warmup_lock.release()
