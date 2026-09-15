from types import SimpleNamespace

import pytest

from backend.app.core.config import settings
from backend.app.services.x_semantic_search import XSemanticSearchService


class FakeDocuments:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get_documents_by_ids(self, ids, limit=5):
        self.calls.append((ids, limit))
        by_id = {str(row["id"]): row for row in self.rows}
        return [by_id[doc_id] for doc_id in ids if doc_id in by_id][:limit]


class FakeVectors:
    def __init__(self, hits=None, error=None):
        self.hits = hits or []
        self.error = error
        self.calls = []

    def search_with_status(self, query, top_k=5):
        self.calls.append((query, top_k))
        return self.hits, self.error


@pytest.mark.asyncio
async def test_search_returns_only_x_rows_and_preserves_vector_order(monkeypatch):
    monkeypatch.setattr(settings, "project_semantic_search_enabled", True)
    documents = FakeDocuments([
        {"id": "x-1", "source": "x", "title": "one"},
        {"id": "g-1", "source": "github", "title": "not x"},
    ])
    vectors = FakeVectors([
        SimpleNamespace(metadata={"id": "x-1", "score": 0.91}),
        SimpleNamespace(metadata={"id": "g-1", "score": 0.88}),
    ])

    result = await XSemanticSearchService(documents=documents, vectors=vectors).search("agent", 10)

    assert result.status == "ok"
    assert result.degraded is False
    assert result.items == [{"id": "x-1", "source": "x", "title": "one", "semantic_score": 0.91}]
    assert vectors.calls == [("agent", 30)]


@pytest.mark.asyncio
async def test_search_exposes_disabled_and_unavailable_states(monkeypatch):
    monkeypatch.setattr(settings, "project_semantic_search_enabled", False)
    disabled = await XSemanticSearchService(
        documents=FakeDocuments([]), vectors=FakeVectors()
    ).search("agent")
    assert disabled.status == "disabled"
    assert disabled.items == []

    monkeypatch.setattr(settings, "project_semantic_search_enabled", True)
    unavailable = await XSemanticSearchService(
        documents=FakeDocuments([]), vectors=FakeVectors(error="milvus offline")
    ).search("agent")
    assert unavailable.status == "unavailable"
    assert unavailable.degraded is True
    assert unavailable.error == "milvus offline"


@pytest.mark.asyncio
async def test_search_rejects_blank_query_without_vector_call(monkeypatch):
    monkeypatch.setattr(settings, "project_semantic_search_enabled", True)
    vectors = FakeVectors()
    result = await XSemanticSearchService(
        documents=FakeDocuments([]), vectors=vectors
    ).search("  \n")
    assert result.status == "invalid_query"
    assert vectors.calls == []
