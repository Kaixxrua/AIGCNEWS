from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.core.config import settings
from backend.app.repositories.project_vector_repo import ProjectVectorRepository
from backend.app.services.search_semantics import normalize_search_query


@dataclass(frozen=True)
class ProjectSemanticHit:
    repo_id: str
    score: float


class ProjectSemanticSearch:
    def __init__(
        self,
        *,
        vectors: ProjectVectorRepository | None = None,
        embeddings: Any = None,
    ) -> None:
        self.vectors = vectors or ProjectVectorRepository()
        self._embeddings = embeddings

    def search_repo_ids(self, query: str) -> list[ProjectSemanticHit]:
        if not settings.project_semantic_search_enabled:
            return []
        query = normalize_search_query(query)[:120]
        if not query:
            return []
        if self._embeddings is None:
            from backend.app.core.model_factory import get_embedding_model

            self._embeddings = get_embedding_model()
        vector = list(self._embeddings.embed_query(query))
        hits = self.vectors.search_repo_ids(
            vector,
            chunk_limit=settings.project_semantic_chunk_limit,
            repo_limit=settings.project_semantic_repo_limit,
            min_score=settings.project_semantic_min_score,
        )
        return [ProjectSemanticHit(repo_id=hit.repo_id, score=hit.score) for hit in hits]
