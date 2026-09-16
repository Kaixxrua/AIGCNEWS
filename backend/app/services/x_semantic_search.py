from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

from backend.app.core.config import settings
from backend.app.repositories.document_repository import DocumentSearchReader
from backend.app.repositories.milvus_repo import MilvusRepository


class XSemanticVectorReader(Protocol):
    def search_with_status(self, query: str, top_k: int = 5) -> tuple[list[Any], str | None]: ...


@dataclass(frozen=True)
class XSemanticSearchResult:
    items: list[dict[str, Any]]
    status: str
    degraded: bool
    error: str | None = None


class XSemanticSearchService:
    """Orchestrate X document semantic search without hiding vector failures."""

    def __init__(
        self,
        *,
        documents: DocumentSearchReader,
        vectors: XSemanticVectorReader | None = None,
    ) -> None:
        self.documents = documents
        self.vectors = vectors or MilvusRepository()

    async def search(self, query: str, limit: int = 20) -> XSemanticSearchResult:
        normalized = " ".join(str(query or "").split())
        if not normalized:
            return XSemanticSearchResult([], "invalid_query", False, "query must not be empty")
        if not settings.project_semantic_search_enabled:
            return XSemanticSearchResult([], "disabled", False)

        hits, error = await asyncio.to_thread(self.vectors.search_with_status, normalized, limit * 3)
        if error:
            return XSemanticSearchResult([], "unavailable", True, error)
        ids: list[str] = []
        scores: dict[str, float] = {}
        for doc in hits:
            metadata = getattr(doc, "metadata", {}) or {}
            doc_id = str(metadata.get("id") or "").strip()
            if doc_id and doc_id not in scores:
                ids.append(doc_id)
                scores[doc_id] = float(metadata.get("score") or 0.0)
        if not ids:
            return XSemanticSearchResult([], "ok", False)
        rows = await asyncio.to_thread(self.documents.get_documents_by_ids, ids, len(ids))
        items = []
        for row in rows:
            if str(row.get("source") or "").lower() != "x":
                continue
            item = dict(row)
            item["semantic_score"] = scores.get(str(item.get("id")), 0.0)
            items.append(item)
            if len(items) >= limit:
                break
        return XSemanticSearchResult(items, "ok", False)
