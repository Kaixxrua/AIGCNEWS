from __future__ import annotations

"""Framework-light dependency composition for ingestion application services."""

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable, Sequence

from backend.app.repositories.application_repository_factory import (
    ApplicationRepositories,
)
from backend.app.repositories.task_repository import IngestionTaskWriter
from backend.app.services.ingestion.base_crawler import BaseCrawler

ResourceFactory = Callable[[], object]
CacheInvalidator = Callable[..., Awaitable[None]]
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
    x_translation_processor: ResourceFactory | None = None


def provide_ingestion_dependencies(
    *,
    repositories: ApplicationRepositories,
    task_writer: IngestionTaskWriter | None = None,
) -> IngestionDependencies:
    """Build production ingestion dependencies without a DI framework."""
    from backend.app.core.config import settings
    from backend.app.repositories.graph_repo import GraphRepository
    from backend.app.repositories.milvus_repo import MilvusRepository
    from backend.app.services.ingestion.arxiv_pdf_downloader import (
        download_and_index_arxiv_pdfs,
    )
    from backend.app.services.ingestion.cache_invalidation import (
        clear_dashboard_cache_safely,
    )

    # 生产形态下本函数由调度器在主 event loop 上同步调用
    # （scheduler._run_single_source_job / _reconcile_* 均 async 于主 loop），
    # 此处捕获的即主 loop；而 cache_invalidator 实际在采集 worker 线程的
    # asyncio.run 一次性 loop 里被 await（pipeline.run_single_source_pipeline）。
    try:
        main_loop = asyncio.get_running_loop()
    except RuntimeError:
        # 无运行 loop 的同步/CLI 调用方：无并发 HTTP 读者，就地执行即可。
        main_loop = None

    async def _clear_and_warm_on_loop(*, new_x_rows: int = 0) -> None:
        """清缓存 + 首屏预热，按新 X 文档行数决定媒体预热。"""
        await clear_dashboard_cache_safely()
        # composition root 允许跨层装配：预热逻辑在 api 层（与路由同源生成 cache key）
        from backend.app.api.dashboard_cache_warmup import warm_dashboard_cache

        await warm_dashboard_cache(repositories)

        # 媒体边缘预热走 detached task：冷图回源最坏 ~80s，不能拖慢采集主流程；
        # 开关关闭时 spawn 返回 None，零行为变更。
        if new_x_rows > 0:
            from backend.app.services.x_media_warmup import spawn_x_media_warmup_task

            spawn_x_media_warmup_task(repositories.documents)

    async def clear_and_warm_dashboard_cache(*, new_x_rows: int = 0) -> None:
        """先清旧 dashboard key，再按前端首屏参数重建热缓存。

        纯删除式失效会让每个采集窗口后的首批用户撞上 ~3s 级冷查询；
        预热在后台把首屏组合重新算好，用户请求始终命中热缓存。
        清缓存与预热均为非致命路径，异常由各自内部兜底。

        关键：当采集把本钩子调度到 worker 线程的 asyncio.run 一次性 loop 上时，
        必须把工作桥回被捕获的主 loop 执行，原因有二：
        - fastapi-cache 的全局 RedisBackend 连接池绑定首次使用它的 loop；在采集
          临时 loop 写缓存会污染连接池，回主 loop 后 HTTP 读报
          "attached to a different loop"，被宽捕获吞成 MISS（2026-08-14 实测
          浏览器 MISS / curl 同 key HIT 的双分裂根因）。
        - 媒体预热 spawn 的 detached task 若挂在采集临时 loop 上，会被
          asyncio.run 收尾的 loop.close() 掐掉，预热日志永不出现。
        桥回主 loop 后两件事都消失：缓存 SET 对 HTTP 读者可见、detached task
        挂在不关闭的主 loop 上得以跑完。
        """
        current_loop = asyncio.get_running_loop()
        if (
            main_loop is not None
            and main_loop is not current_loop
            and main_loop.is_running()
        ):
            # 采集线程临时 loop：整体桥到主 loop 执行并等待其完成。
            # asyncio.to_thread 让主 loop 在等待采集期间保持空闲，故不会死锁。
            await asyncio.wrap_future(
                asyncio.run_coroutine_threadsafe(
                    _clear_and_warm_on_loop(new_x_rows=new_x_rows), main_loop
                )
            )
            return
        # 同 loop（单测）或无主 loop（CLI）：就地执行，行为与原先一致。
        await _clear_and_warm_on_loop(new_x_rows=new_x_rows)
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

    crawler_factories: list[CrawlerFactory] = [
        ArxivCrawler,
        GitHubCrawler,
        NewsCrawler,
        ProductHuntCrawler,
        HackerNewsCrawler,
        # DailyHot 上游为编排内网自托管服务；未部署时采集返回 error 不影响其他源。
        DailyHotCrawler,
    ]
    # 可插拔源：开关关闭时不注册爬虫，采集管道整体跳过该源；
    # X watchlist 与凭据均走数据库（D3 接缝）：空表时仓储按 env 自举，
    # 监控页 /ops/x-watch-accounts 与 /ops/x-credentials 管理后即成为唯一事实源。
    if settings.x_source_enabled:
        crawler_factories.append(
            lambda: XCrawler(
                watchlist_provider=repositories.x_watch_accounts.list_enabled_x_handles,
                credential_provider=repositories.x_credentials.list_enabled_x_credentials,
            ),
        )

    from backend.app.services.ingestion.x_translation_service import (
        XTranslationProcessor,
    )

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
        cache_invalidator=clear_and_warm_dashboard_cache,
        crawler_factories=tuple(crawler_factories),
        x_translation_processor=lambda: XTranslationProcessor(
            repositories.x_translation_tasks
        ),
    )
