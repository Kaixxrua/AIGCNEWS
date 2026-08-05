from __future__ import annotations

from typing import Any, Protocol


class DocumentWriter(Protocol):
    """Persist documents while preserving caller-visible normalization."""

    def upsert_document(self, doc: dict[str, Any]) -> None: ...

    def update_document_pdf_path(self, doc_id: str, local_pdf_path: str) -> None: ...

    def delete_document(self, doc_id: str) -> bool: ...


class DocumentSearchReader(Protocol):
    """Search document content with stable pagination and ordering."""

    def search_document_page(
        self,
        query: str,
        *,
        source: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]: ...

    def search_documents(
        self,
        query: str,
        limit: int = 20,
        *,
        source: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_existing_document_summaries(
        self,
        *,
        ids: list[str] | None = None,
        urls: list[str] | None = None,
        titles: list[str] | None = None,
    ) -> dict[str, str]: ...


class DocumentRetrievalReader(Protocol):
    """Read document rows for exact-ID and title-token retrieval."""

    def get_documents_by_ids(
        self,
        document_ids: list[str],
        limit: int = 5,
    ) -> list[dict[str, Any]]: ...

    def get_documents_by_title_tokens(
        self,
        tokens: list[str],
        *,
        min_matches: int = 3,
        limit: int = 5,
    ) -> list[dict[str, Any]]: ...


class DocumentRankingReader(Protocol):
    """Read the ranked document lists consumed by RAG database tools."""

    def get_today_ranked_documents(
        self,
        limit: int = 15,
        *,
        source: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_knowledge_ranked_documents(
        self,
        limit: int = 50,
        *,
        source: str | None = None,
    ) -> list[dict[str, Any]]: ...


class PapersReader(Protocol):
    """Read the narrow document projections consumed by Papers REST routes."""

    def get_today_top_arxiv_documents(self) -> list[dict[str, Any]]: ...

    def get_paper_detail(self, paper_id: str) -> dict[str, Any] | None: ...

    def get_paper_pdf_source(self, paper_id: str) -> dict[str, Any] | None: ...


class DocumentFeedReader(Protocol):
    """Read ranked and recently ingested document feeds."""

    def get_top_documents(
        self,
        limit: int = 10,
        source_type: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_latest_documents(self, limit: int = 10) -> list[dict[str, Any]]: ...


class DocumentStatisticsReader(Protocol):
    """Read aggregate document statistics."""

    def get_document_count(self) -> int: ...

    def get_source_counts(self) -> dict[str, int]: ...

    def get_today_document_count(self) -> int: ...


class DocumentAdminWriter(Protocol):
    """Perform destructive document administration."""

    def clear_all_documents(self) -> int: ...


class DocumentRepository(
    DocumentWriter,
    DocumentSearchReader,
    DocumentRetrievalReader,
    DocumentRankingReader,
    PapersReader,
    DocumentFeedReader,
    DocumentStatisticsReader,
    DocumentAdminWriter,
    Protocol,
):
    """Combined document persistence boundary."""
