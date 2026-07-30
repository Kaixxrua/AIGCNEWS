from __future__ import annotations

from typing import Protocol

from langchain_core.documents import Document


class VectorRetrievalReader(Protocol):
    """Vector retrieval boundary used by hybrid search."""

    def is_available(self) -> bool: ...

    def search(self, query: str, top_k: int = 5) -> list[Document]: ...

    def search_by_source(self, source: str, top_k: int = 3) -> list[Document]: ...


class GraphRetrievalReader(Protocol):
    """Graph retrieval boundary used by hybrid search."""

    def search(self, keywords: list[str], limit: int = 5) -> list[Document]: ...


class RagRetriever(Protocol):
    """Asynchronous retrieval boundary used by answer generation."""

    async def search(self, query: str, top_k: int = 5) -> list[Document]: ...
