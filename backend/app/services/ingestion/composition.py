from __future__ import annotations

"""Framework-light dependency composition for ingestion application services."""

from dataclasses import dataclass
from typing import Awaitable, Callable, Sequence

from backend.app.repositories.application_repository_factory import (
    ApplicationRepositories,
)
from backend.app.repositories.task_repository import IngestionTaskWriter
from backend.app.services.ingestion.base_crawler import BaseCrawler

ResourceFactory = Callable[[], object]
CacheInvalidator = Callable[[], Awaitable[None]]
PdfIndexer = Callable[..., tuple[int, int]]
CrawlerFactory = Callable[[], BaseCrawler]


@dataclass(frozen=True)
class IngestionDependencies:
    """Ingestion composition with explicit resource ownership.

    ``repositories`` and ``task_writer`` are borrowed application-lifetime resources and
    must not be closed by ingestion. Every ``*_factory`` returns a resource owned by the
    operation that invokes it; closable resources must be closed by that operation.
    """

    repositories: ApplicationRepositories
    task_writer: IngestionTaskWriter
    vector_writer_factory: ResourceFactory
    graph_extractor_factory: ResourceFactory
    graph_writer_factory: ResourceFactory
    pdf_vector_writer_factory: ResourceFactory
    pdf_indexer: PdfIndexer
    cache_invalidator: CacheInvalidator
    crawler_factories: Sequence[CrawlerFactory]


def provide_ingestion_dependencies(
    *,
    repositories: ApplicationRepositories,
    task_writer: IngestionTaskWriter | None = None,
) -> IngestionDependencies:
    """Build production ingestion dependencies without a DI framework."""
    from backend.app.repositories.graph_repo import GraphRepository
    from backend.app.repositories.milvus_repo import MilvusRepository
    from backend.app.services.ingestion.arxiv_pdf_downloader import (
        download_and_index_arxiv_pdfs,
    )
    from backend.app.services.ingestion.cache_invalidation import (
        clear_dashboard_cache_safely,
    )
    from backend.app.services.ingestion.crawlers import (
        ArxivCrawler,
        DailyHotCrawler,
        GitHubCrawler,
        HackerNewsCrawler,
        NewsCrawler,
        ProductHuntCrawler,
        XCrawler,
    )
    from backend.app.services.ingestion.graph_extractor import GraphExtractor

    return IngestionDependencies(
        repositories=repositories,
        task_writer=(
            repositories.ingestion_tasks if task_writer is None else task_writer
        ),
        vector_writer_factory=MilvusRepository,
        graph_extractor_factory=GraphExtractor,
        graph_writer_factory=GraphRepository,
        pdf_vector_writer_factory=MilvusRepository,
        pdf_indexer=download_and_index_arxiv_pdfs,
        cache_invalidator=clear_dashboard_cache_safely,
        crawler_factories=(
            ArxivCrawler,
            GitHubCrawler,
            NewsCrawler,
            ProductHuntCrawler,
            HackerNewsCrawler,
            # DailyHot 上游为编排内网自托管服务；未部署时采集返回 error 不影响其他源。
            DailyHotCrawler,
            # X watchlist 与凭据均走数据库（D3 接缝）：空表时仓储按 env 自举，
            # 监控页 /ops/x-watch-accounts 与 /ops/x-credentials 管理后即成为唯一事实源。
            lambda: XCrawler(
                watchlist_provider=repositories.x_watch_accounts.list_enabled_x_handles,
                credential_provider=repositories.x_credentials.list_enabled_x_credentials,
            ),
        ),
    )
