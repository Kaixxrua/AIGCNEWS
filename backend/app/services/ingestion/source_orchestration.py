from __future__ import annotations

import asyncio
import logging
from typing import Protocol

from backend.app.services.ingestion.base_crawler import BaseCrawler, CrawlResult

logger = logging.getLogger(__name__)

_PERIODS = ("daily", "weekly", "monthly")

# X rolling-window 完整性失败的稳定错误前缀：crawler fail-closed 产出。
# 该故障必须穿透「其他源/其他周期成功」的掩盖——X 是新发布内容的
# 关键入口，rolling 不完整意味着已发布推文可能漏采，绝不能让整轮
# 任务以 success 收场。
_X_WINDOW_INCOMPLETE_PREFIX = "x_window_incomplete"


def _is_critical_x_failure(source_name: str, error: str | None) -> bool:
    """是否为 X rolling-window 完整性失败（需穿透整轮成功掩盖）。"""
    return source_name == "x" and bool(error) and str(error).startswith(
        _X_WINDOW_INCOMPLETE_PREFIX
    )


class IngestionOrchestrationHost(Protocol):
    limit: int
    target_date: str | None
    github_ingestion: object
    documents: object
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
    ) -> object: ...

    def _start_arxiv_pdf_background(self, papers: list[dict]) -> None: ...

    async def _clear_dashboard_cache(self, *, new_x_rows: int = 0) -> None: ...


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
            corroboration_window,
        )

        # trending 落库后触发重算，正是佐证数据最新的时候；佐证失败按无佐证打标
        corroborated: set[str] | None = None
        documents = getattr(self.host, "documents", None)
        if documents is not None:
            since, until = corroboration_window(crawl_result.snapshot_date)
            try:
                corroborated = await asyncio.to_thread(
                    documents.list_github_repo_mentions,
                    since_date=since,
                    until_date=until,
                )
            except Exception as exc:  # noqa: BLE001 - 佐证失败不阻塞指标重算
                logger.warning("[Orchestrator][github_daily] 反作弊佐证查询失败（按无佐证打标）: %s", exc)

        metric_result = await asyncio.to_thread(
            compute_github_daily_metrics,
            metric_date=crawl_result.snapshot_date,
            repo_ids=hit_result["repo_ids"],
            corroborated_repo_ids=corroborated,
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
            # 源缺席有两种：未注册（未知源名），或构造期失败被跳过
            # （如可插拔源插件缺失）——后者必须带上构造失败原因，否则
            # 调度日志只剩"未知数据源"，无法定位到插件层。
            construction_errors: list[str] = (
                getattr(self.host, "crawler_construction_errors", None) or []
            )
            detail = ""
            if construction_errors:
                detail = "；另有爬虫工厂构造失败: " + " | ".join(construction_errors)
            raise ValueError(
                f"未知数据源 '{source_name}'，可用: {self.host.registered_sources}{detail}"
            )

        task_name = (
            f"single:{source_name}:{self.host.target_date}"
            if self.host.target_date
            else f"single:{source_name}"
        )
        task_id = self.host._create_task(task_name)
        total = 0
        new_x_rows = 0
        x_ingested_total = 0
        failed_periods: list[tuple[str, str]] = []
        critical_x_failures: list[str] = []
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
                    failed_periods.append((period, crawl_result.error or "unknown"))
                    if _is_critical_x_failure(source_name, crawl_result.error):
                        critical_x_failures.append(crawl_result.error or "unknown")
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
                ingest_result = await self.host._enrich_and_ingest(
                    source_name=source_name,
                    papers=crawl_result.items,
                    task_id=task_id,
                    log_label=f"{source_name}_{period}",
                    snapshot_date=crawl_result.snapshot_date,
                )
                total += int(ingest_result)
                new_x_rows += int(getattr(ingest_result, "new_x_rows", 0))
                if source_name == "x":
                    x_ingested_total += int(ingest_result)
                if source_name == "arxiv":
                    arxiv_papers_for_pdf.extend(
                        paper
                        for paper in crawl_result.items
                        if paper.get("arxiv_id")
                    )

            if source_name == "arxiv":
                self.host._start_arxiv_pdf_background(arxiv_papers_for_pdf)

            if critical_x_failures:
                # X rolling-window 不完整 = 已发布推文可能漏采。无论其他周期/
                # 源是否入库，整轮必须记 failed 并保留稳定错误标记，不触发
                # 成功专属的 cache clear/warmup。
                error_msg = "; ".join(critical_x_failures)
                self.host._finish_task(
                    task_id, status="failed", error_msg=error_msg, item_count=total
                )
                logger.error(
                    "[Orchestrator] X rolling-window 不完整，单源整轮失败: %s",
                    error_msg,
                )
                return {
                    source_name: total,
                    "ingested_total": total,
                    "new_x_rows": new_x_rows,
                }

            if total == 0 and failed_periods:
                # 单源整轮零入库且存在采集错误：不能记 success，否则
                # should_run_smart_ingestion 会把它当作今日已成功而跳过重试。
                detail = "; ".join(f"{period}: {error}" for period, error in failed_periods)
                error_msg = f"{source_name} 整轮零入库（{detail}）"
                self.host._finish_task(task_id, status="failed", error_msg=error_msg)
                logger.error("[Orchestrator] 单源采集零入库: %s", error_msg)
                return {source_name: 0, "ingested_total": 0, "new_x_rows": 0}

            self.host._finish_task(task_id, status="success", item_count=total)
            try:
                cache_cleared = False
                if total > 0:
                    if source_name == "x":
                        if new_x_rows > 0:
                            await self.host._clear_dashboard_cache(
                                new_x_rows=new_x_rows
                            )
                            cache_cleared = True
                        else:
                            logger.info(
                                "[Orchestrator] X 无新增文档，跳过 dashboard cache invalidation."
                            )
                    else:
                        await self.host._clear_dashboard_cache()
                        cache_cleared = True
                    if cache_cleared:
                        logger.info(
                            "[Orchestrator] dashboard cache cleared after single-source ingest."
                        )
                else:
                    logger.info("[Orchestrator] no rows ingested; dashboard cache kept.")
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

        return {
            source_name: total,
            "ingested_total": total,
            "new_x_rows": new_x_rows,
        }

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
        new_x_rows = 0
        x_ingested_total = 0
        crawl_errors: list[str] = []
        critical_x_failures: list[str] = []
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
                        crawl_errors.append(f"{source_key}/{period}: {result}")
                        continue

                    crawl_result: CrawlResult = result
                    if not crawl_result.ok:
                        logger.warning(
                            "[Orchestrator][%s] %s 榜采集失败: %s",
                            source_key,
                            period,
                            crawl_result.error,
                        )
                        crawl_errors.append(
                            f"{source_key}/{period}: {crawl_result.error or 'unknown'}"
                        )
                        if _is_critical_x_failure(source_key, crawl_result.error):
                            critical_x_failures.append(
                                f"{source_key}/{period}: {crawl_result.error}"
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
                    ingest_result = await self.host._enrich_and_ingest(
                        source_name=source_key,
                        papers=crawl_result.items,
                        task_id=task_id,
                        log_label=f"{source_key}_{period}",
                        snapshot_date=crawl_result.snapshot_date,
                    )
                    count = int(ingest_result)
                    stats[source_key] += count
                    total += count
                    new_x_rows += int(getattr(ingest_result, "new_x_rows", 0))
                    if source_key == "x":
                        x_ingested_total += count
                    if source_key == "arxiv":
                        arxiv_papers_for_pdf.extend(
                            paper
                            for paper in crawl_result.items
                            if paper.get("arxiv_id")
                        )

                logger.info("[Orchestrator] ── %s 周期处理完成 ──", period)

            if total == 0 and crawl_errors:
                # 全源整轮零入库且存在采集错误：记 failed 而非 success，
                # 让智能采集重试并让运维能看到整轮失败。
                error_msg = f"整轮零入库（{'；'.join(crawl_errors[:5])}）"
                self.host._finish_task(task_id, status="failed", error_msg=error_msg)
                logger.error("[Orchestrator] 全源采集零入库: %s", error_msg)
                stats["ingested_total"] = 0
                stats["new_x_rows"] = 0
                return stats

            if critical_x_failures:
                # GitHub/news 等其他源成功不能把 X rolling-window 不完整
                # 伪装成整轮 success。整轮记 failed、保留已入库计数，并跳过
                # 成功专属的 cache clear 与 PDF 后台启动（避免误触发）。
                error_msg = "; ".join(critical_x_failures)
                self.host._finish_task(
                    task_id, status="failed", error_msg=error_msg, item_count=total
                )
                logger.error(
                    "[Orchestrator] X rolling-window 不完整（其他源已入库 %d 条仍记失败）: %s",
                    total,
                    error_msg,
                )
                stats["ingested_total"] = total
                stats["new_x_rows"] = new_x_rows
                return stats

            self.host._finish_task(task_id, status="success", item_count=total)
            try:
                cache_cleared = False
                if total > 0:
                    non_x_ingested_total = total - x_ingested_total
                    if new_x_rows > 0:
                        await self.host._clear_dashboard_cache(
                            new_x_rows=new_x_rows
                        )
                        cache_cleared = True
                    elif non_x_ingested_total > 0:
                        await self.host._clear_dashboard_cache()
                        cache_cleared = True
                    else:
                        logger.info(
                            "[Orchestrator] X 无新增文档，跳过 dashboard cache invalidation."
                        )
                    if cache_cleared:
                        logger.info(
                            "[Orchestrator] dashboard cache cleared after full ingest."
                        )
                else:
                    logger.info("[Orchestrator] no rows ingested; dashboard cache kept.")
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
        stats["new_x_rows"] = new_x_rows
        return stats
