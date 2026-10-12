from __future__ import annotations

from typing import Any, Protocol


class DocumentWriter(Protocol):
    """Persist documents while preserving caller-visible normalization."""

    def upsert_document(self, doc: dict[str, Any]) -> None: ...

    def upsert_x_document_with_translation_targets(
        self,
        doc: dict[str, Any],
        targets: list[dict[str, Any]],
    ) -> bool: ...

    def update_document_pdf_path(self, doc_id: str, local_pdf_path: str) -> None: ...

    def delete_document(self, doc_id: str) -> bool: ...

    def delete_documents(self, doc_ids: list[str]) -> list[str]: ...


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

    def get_paper_by_arxiv_id(self, arxiv_id: str) -> dict[str, Any] | None: ...

    def get_paper_pdf_source(self, paper_id: str) -> dict[str, Any] | None: ...


class DocumentFeedReader(Protocol):
    """Read ranked and recently ingested document feeds."""

    def get_top_documents(
        self,
        limit: int = 10,
        source_type: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def get_recent_top_documents(
        self,
        *,
        source_type: str,
        since_date: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]: ...

    def get_latest_documents(self, limit: int = 10) -> list[dict[str, Any]]: ...


class DocumentRecentReader(Protocol):
    """Read documents published within a trailing time window (rolling N hours).

    窗口/排序键契约：COALESCE(published_at, published_date, created_at)——
    与展示层 pubDate/lastmod 同一回退链（X=推文时间，榜单源=每日上榜刷新
    的 published_date，其余=业务日期）；并 OR created_at >= since 兜底
    date-only 键边界日漏检与「业务日期滞后于入池」（arXiv 老论文新收录）。
    until_iso 仅约束主键（X 看板 days_back 依赖其对 published_at 精确）。
    keyset_after 只对 X 分支生效：上一页末行的排序位置
    ``(published_at, score, id)``，实现按严格递减续查，不传时返回第一页。
    x_handles 只对 X 分支生效，按采集归属账号（优先转发者）在 LIMIT 前筛选。
    """

    def list_recent_by_source(
        self,
        source: str,
        *,
        since_iso: str,
        until_iso: str | None = None,
        limit: int = 500,
        keyset_after: tuple[str, float, str] | None = None,
        x_handles: list[str] | None = None,
    ) -> list[dict[str, Any]]: ...


class DocumentGithubMentionReader(Protocol):
    """Read GitHub repo slugs mentioned by non-github channel documents."""

    def list_github_repo_mentions(
        self,
        *,
        since_date: str,
        until_date: str,
    ) -> set[str]: ...


class DocumentXSnapshotBackfillReader(Protocol):
    """Read x documents (id/published_at/scores) for historical snapshot rebuild."""

    def list_x_snapshot_backfill_rows(self) -> list[dict[str, Any]]: ...


class DocumentXJanitorReader(Protocol):
    """Read x documents (id/url/quote) for deleted-tweet probing."""

    def list_x_documents_for_probe(self, limit: int) -> list[dict[str, Any]]: ...


class DocumentXJanitorWriter(Protocol):
    """Clear quote cards on x documents whose quoted tweet was author-deleted."""

    def clear_quotes_for_docs(self, doc_ids: list[str]) -> list[str]: ...


class DocumentStatisticsReader(Protocol):
    """Read aggregate document statistics."""

    def get_document_count(self) -> int: ...

    def get_source_counts(self) -> dict[str, int]: ...

    # 「今日更新」计数：「今日」为 scheduler_timezone（默认 Asia/Shanghai）
    # 自然日；非 github 来源按 documents.created_at 落入当日窗口计数，
    # github 部分按 github_repo_enrichments 当日 enriched_at 且
    # status='succeeded' 的入库项目计数（github_library_total 的当日增量）。
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
