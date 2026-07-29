from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from backend.app.services.ingestion.base_crawler import BaseCrawler, CrawlResult

logger = logging.getLogger(__name__)

_PERIODS = ("daily", "weekly", "monthly")


class IngestionOrchestrationHost(Protocol):
    limit: int
    target_date: str | None
    github_ingestion: object
    _crawlers: dict[str, BaseCrawler]

    @property
    def registered_sources(self) -> list[str]: ...

    def _create_task(self, task_name: str) -> int: ...

    def _finish_task(
        self,
        task_id: int,
        *,
        status: str = "success",
        error_msg: str | None = None,
        item_count: int = 0,
    ) -> None: ...

    async def _enrich_and_ingest(
        self,
        source_name: str,
        papers: list[dict],
        task_id: int,
        log_label: str | None = None,
        snapshot_date: str | None = None,
    ) -> int: ...

    def _start_arxiv_pdf_background(self, papers: list[dict]) -> None: ...

    async def _clear_dashboard_cache(self) -> None: ...


class MultiSourceIngestionRuntime:
    """Coordinate period/source execution without owning projection or persistence."""

    def __init__(self, host: IngestionOrchestrationHost) -> None:
        self.host = host

    @staticmethod
    def _set_period_flags(papers: list[dict], period: str) -> None:
        for paper in papers:
            paper["in_daily"] = int(period == "daily")
            paper["in_weekly"] = int(period == "weekly")
            paper["in_monthly"] = int(period == "monthly")

    async def _record_github_observation(
        self,
        crawl_result: CrawlResult,
        period: str,
    ) -> None:
        from backend.app.services.ingestion.github_hot_service import (
            record_github_trending_hits,
        )

        hit_result = await asyncio.to_thread(
            record_github_trending_hits,
            crawl_result.items,
            period=period,
            observed_date=crawl_result.snapshot_date,
            db=self.host.github_ingestion,
        )
        if period != "daily" or not hit_result["repo_ids"]:
            return

        from backend.app.services.ingestion.github_project_metrics_service import (
            compute_github_daily_metrics,
        )

        metric_result = await asyncio.to_thread(
            compute_github_daily_metrics,
            metric_date=crawl_result.snapshot_date,
            repo_ids=hit_result["repo_ids"],
            db=self.host.github_ingestion,
        )
        logger.info(
            "[Orchestrator][github_daily] Trending 增长已同步：hits=%d metrics=%d fallback=%d",
            hit_result["hits"],
            metric_result["rows"],
            metric_result["trending_fallback"],
        )

    async def run_single_source(
        self,
        source_name: str,
        periods: list[str] | None = None,
    ) -> dict[str, int]:
        crawler = self.host._crawlers.get(source_name)
        if crawler is None:
            raise ValueError(
                f"未知数据源 '{source_name}'，可用: {self.host.registered_sources}"
            )

        task_name = (
            f"single:{source_name}:{self.host.target_date}"
            if self.host.target_date
            else f"single:{source_name}"
        )
        task_id = self.host._create_task(task_name)
        total = 0
        arxiv_papers_for_pdf: list[dict] = []

        try:
            for period in periods or list(_PERIODS):
                if period not in crawler.supported_periods:
                    logger.info(
                        "[Orchestrator][%s] 不支持 %s 周期，跳过。",
                        source_name,
                        period,
                    )
                    continue

                crawl_result = await crawler.fetch(
                    period=period,
                    limit=self.host.limit,
                    target_date=self.host.target_date,
                )
                if not crawl_result.ok:
                    logger.warning(
                        "[Orchestrator][%s] %s 榜采集失败: %s",
                        source_name,
                        period,
                        crawl_result.error,
                    )
                    continue
                if not crawl_result.items:
                    logger.info(
                        "[Orchestrator][%s] %s 榜无数据。", source_name, period
                    )
                    continue

                self._set_period_flags(crawl_result.items, period)
                if source_name == "github":
                    await self._record_github_observation(crawl_result, period)

                logger.info(
                    "[Orchestrator][%s] %s 榜采集 %d 条，开始 enrich+ingest...",
                    source_name,
                    period,
                    len(crawl_result.items),
                )
                total += await self.host._enrich_and_ingest(
                    source_name=source_name,
                    papers=crawl_result.items,
                    task_id=task_id,
                    log_label=f"{source_name}_{period}",
                    snapshot_date=crawl_result.snapshot_date,
                )
                if source_name == "arxiv":
                    arxiv_papers_for_pdf.extend(
                        paper
                        for paper in crawl_result.items
                        if paper.get("arxiv_id")
                    )

            if source_name == "arxiv":
                self.host._start_arxiv_pdf_background(arxiv_papers_for_pdf)

            self.host._finish_task(task_id, status="success", item_count=total)
            try:
                await self.host._clear_dashboard_cache()
                logger.info(
                    "[Orchestrator] dashboard cache cleared after single-source ingest."
                )
            except Exception as exc:
                logger.warning(
                    "[Orchestrator] 清理 dashboard cache 失败（非致命）: %s", exc
                )
            logger.info(
                "[Orchestrator] 单源采集完成: %s → %d 条入库。",
                source_name,
                total,
            )
        except Exception as exc:
            self.host._finish_task(task_id, status="failed", error_msg=str(exc))
            logger.error("[Orchestrator] 单源采集失败 %s: %s", source_name, exc)
            raise

        return {source_name: total, "ingested_total": total}

    async def run_all(self) -> dict[str, int]:
        task_name = (
            f"date_ingest:{self.host.target_date}"
            if self.host.target_date
            else "multi_source_ingest"
        )
        task_id = self.host._create_task(task_name)
        stats = {name: 0 for name in self.host._crawlers}
        stats["huggingface"] = 0
        total = 0
        arxiv_papers_for_pdf: list[dict] = []

        try:
            logger.info(
                "[Orchestrator] 按周期串行采集 %d 个数据源（limit=%d, target_date=%s）...",
                len(self.host._crawlers),
                self.host.limit,
                self.host.target_date or "today",
            )
            for period in _PERIODS:
                logger.info("[Orchestrator] ── 开始 %s 周期采集 ──", period)
                period_crawl_tasks = {
                    name: crawler.fetch(
                        period=period,
                        limit=self.host.limit,
                        target_date=self.host.target_date,
                    )
                    for name, crawler in self.host._crawlers.items()
                    if period in crawler.supported_periods
                }
                if not period_crawl_tasks:
                    logger.info(
                        "[Orchestrator] %s 周期无可用 crawler，跳过。", period
                    )
                    continue

                gathered = await asyncio.gather(
                    *period_crawl_tasks.values(), return_exceptions=True
                )
                for source_key, result in zip(period_crawl_tasks, gathered):
                    if isinstance(result, Exception):
                        logger.error(
                            "[Orchestrator][%s] %s 榜采集异常: %s",
                            source_key,
                            period,
                            result,
                        )
                        continue

                    crawl_result: CrawlResult = result
                    if not crawl_result.ok:
                        logger.warning(
                            "[Orchestrator][%s] %s 榜采集失败: %s",
                            source_key,
                            period,
                            crawl_result.error,
                        )
                        continue
                    if not crawl_result.items:
                        logger.info(
                            "[Orchestrator][%s] %s 榜无数据。",
                            source_key,
                            period,
                        )
                        continue

                    self._set_period_flags(crawl_result.items, period)
                    logger.info(
                        "[Orchestrator][%s] %s 榜采集 %d 条，开始 enrich+ingest...",
                        source_key,
                        period,
                        len(crawl_result.items),
                    )
                    count = await self.host._enrich_and_ingest(
                        source_name=source_key,
                        papers=crawl_result.items,
                        task_id=task_id,
                        log_label=f"{source_key}_{period}",
                        snapshot_date=crawl_result.snapshot_date,
                    )
                    stats[source_key] += count
                    total += count
                    if source_key == "arxiv":
                        arxiv_papers_for_pdf.extend(
                            paper
                            for paper in crawl_result.items
                            if paper.get("arxiv_id")
                        )

                logger.info("[Orchestrator] ── %s 周期处理完成 ──", period)

            self.host._finish_task(task_id, status="success", item_count=total)
            try:
                await self.host._clear_dashboard_cache()
                logger.info(
                    "[Orchestrator] dashboard cache cleared after full ingest."
                )
            except Exception as exc:
                logger.warning(
                    "[Orchestrator] 清理 dashboard cache 失败（非致命）: %s", exc
                )
            logger.info(
                "[Orchestrator] 采集完成，%d 源共 %d 条文档入库（按周期串行）。",
                len(self.host._crawlers),
                total,
            )
            self.host._start_arxiv_pdf_background(arxiv_papers_for_pdf)
        except Exception as exc:
            self.host._finish_task(task_id, status="failed", error_msg=str(exc))
            logger.error("[Orchestrator] ERROR: %s", exc)
            raise

        stats["ingested_total"] = total
        return stats
