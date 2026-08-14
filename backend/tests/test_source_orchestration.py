"""source_orchestration：多源采集编排契约测试。

验证 MultiSourceIngestionRuntime 在 FakeHost 之上的行为：
  - 周期 flag 标注与不支持周期跳过
  - 任务生命周期（create / finish success / finish failed）
  - github 观测记录仅 daily 触发 metrics
  - arxiv PDF 后台任务仅收集带 arxiv_id 的条目
  - run_all 的 gather 异常隔离与统计聚合
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from backend.app.services.ingestion.base_crawler import CrawlResult
from backend.app.services.ingestion.source_orchestration import (
    MultiSourceIngestionRuntime,
)


def _result(
    source: str,
    period: str,
    items: list[dict] | None = None,
    *,
    error: str | None = None,
    snapshot_date: str = "2024-03-02",
) -> CrawlResult:
    return CrawlResult(
        source=source,
        source_channel=f"{source}_{period}_html",
        snapshot_date=snapshot_date,
        period=period,
        items=items or [],
        error=error,
    )


class FakeCrawler:
    """按周期回放预设结果的爬虫替身；fetch 可抛异常（绕过基类容错）。"""

    def __init__(
        self,
        source: str,
        supported_periods: list[str],
        results: dict[str, CrawlResult] | None = None,
        *,
        raise_exc: Exception | None = None,
    ) -> None:
        self.source = source
        self.supported_periods = supported_periods
        self._results = results or {}
        self._raise_exc = raise_exc
        self.fetch_calls: list[dict[str, Any]] = []

    async def fetch(self, *, period: str, limit: int, target_date: str | None = None) -> CrawlResult:
        self.fetch_calls.append({"period": period, "limit": limit, "target_date": target_date})
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._results.get(period, _result(self.source, period))


class FakeHost:
    """IngestionOrchestrationHost 替身：记录任务与下游调用。"""

    def __init__(
        self,
        crawlers: dict[str, FakeCrawler],
        *,
        limit: int = 7,
        target_date: str | None = None,
        fail_enrich: bool = False,
        fail_cache_clear: bool = False,
    ) -> None:
        self.limit = limit
        self.target_date = target_date
        self.github_ingestion = object()
        self._crawlers = crawlers
        self._fail_enrich = fail_enrich
        self._fail_cache_clear = fail_cache_clear
        self.created_tasks: list[str] = []
        self.finished: list[dict[str, Any]] = []
        self.enriched: list[dict[str, Any]] = []
        self.pdf_started: list[list[dict]] = []
        self.cache_cleared = 0

    @property
    def registered_sources(self) -> list[str]:
        return list(self._crawlers)

    def _create_task(self, task_name: str) -> int:
        self.created_tasks.append(task_name)
        return len(self.created_tasks)

    def _finish_task(
        self,
        task_id: int,
        *,
        status: str = "success",
        error_msg: str | None = None,
        item_count: int = 0,
    ) -> None:
        self.finished.append(
            {"task_id": task_id, "status": status, "error_msg": error_msg, "item_count": item_count}
        )

    async def _enrich_and_ingest(
        self,
        source_name: str,
        papers: list[dict],
        task_id: int,
        log_label: str | None = None,
        snapshot_date: str | None = None,
    ) -> int:
        if self._fail_enrich:
            raise RuntimeError("enrich down")
        self.enriched.append(
            {
                "source_name": source_name,
                "papers": papers,
                "task_id": task_id,
                "log_label": log_label,
                "snapshot_date": snapshot_date,
            }
        )
        return len(papers)

    def _start_arxiv_pdf_background(self, papers: list[dict]) -> None:
        self.pdf_started.append(papers)

    async def _clear_dashboard_cache(self) -> None:
        if self._fail_cache_clear:
            raise RuntimeError("cache clear down")
        self.cache_cleared += 1


class TestSetPeriodFlags:
    def test_marks_only_current_period(self) -> None:
        papers = [{"title": "T"}]
        MultiSourceIngestionRuntime._set_period_flags(papers, "weekly")
        assert papers[0]["in_daily"] == 0
        assert papers[0]["in_weekly"] == 1
        assert papers[0]["in_monthly"] == 0


class TestRunSingleSource(unittest.IsolatedAsyncioTestCase):
    async def test_unknown_source_raises_value_error(self) -> None:
        host = FakeHost({"news": FakeCrawler("news", ["daily"])})
        runtime = MultiSourceIngestionRuntime(host)
        with self.assertRaises(ValueError) as ctx:
            await runtime.run_single_source("nope")
        assert "未知数据源 'nope'" in str(ctx.exception)
        assert host.created_tasks == []

    async def test_happy_path_skips_unsupported_periods(self) -> None:
        items = [{"title": "A"}, {"title": "B"}]
        crawler = FakeCrawler("news", ["daily"], {"daily": _result("news", "daily", items)})
        host = FakeHost({"news": crawler}, target_date="2024-03-02")
        runtime = MultiSourceIngestionRuntime(host)

        result = await runtime.run_single_source("news")

        assert result == {"news": 2, "ingested_total": 2}
        assert host.created_tasks == ["single:news:2024-03-02"]
        # 仅 daily 支持 → 只抓取一次；weekly/monthly 被跳过
        assert [c["period"] for c in crawler.fetch_calls] == ["daily"]
        assert crawler.fetch_calls[0]["limit"] == 7
        assert crawler.fetch_calls[0]["target_date"] == "2024-03-02"
        enrich = host.enriched[0]
        assert enrich["source_name"] == "news"
        assert enrich["log_label"] == "news_daily"
        assert enrich["snapshot_date"] == "2024-03-02"
        assert enrich["task_id"] == 1
        assert [(p["in_daily"], p["in_weekly"], p["in_monthly"]) for p in enrich["papers"]] == [
            (1, 0, 0),
            (1, 0, 0),
        ]
        assert host.finished == [{"task_id": 1, "status": "success", "error_msg": None, "item_count": 2}]
        assert host.cache_cleared == 1
        assert host.pdf_started == []  # 非 arxiv 源不触发 PDF 后台任务

    async def test_crawl_error_and_empty_items_are_skipped(self) -> None:
        crawler = FakeCrawler(
            "news",
            ["daily", "weekly", "monthly"],
            {
                "daily": _result("news", "daily", error="boom-daily"),
                "weekly": _result("news", "weekly", []),
                "monthly": _result("news", "monthly", [{"title": "M"}]),
            },
        )
        host = FakeHost({"news": crawler})
        runtime = MultiSourceIngestionRuntime(host)

        result = await runtime.run_single_source("news")

        assert result == {"news": 1, "ingested_total": 1}
        assert [e["log_label"] for e in host.enriched] == ["news_monthly"]
        assert host.finished[0]["status"] == "success"
        assert host.finished[0]["item_count"] == 1

    async def test_github_metrics_only_for_daily(self) -> None:
        crawler = FakeCrawler(
            "github",
            ["daily", "weekly"],
            {
                "daily": _result("github", "daily", [{"full_name": "o/r"}]),
                "weekly": _result("github", "weekly", [{"full_name": "o/r2"}]),
            },
        )
        host = FakeHost({"github": crawler})
        runtime = MultiSourceIngestionRuntime(host)
        record_calls: list[dict[str, Any]] = []
        metrics_calls: list[dict[str, Any]] = []

        def fake_record(items: list, *, period: str, observed_date: str, db: Any) -> dict[str, Any]:
            record_calls.append({"period": period, "observed_date": observed_date, "db": db})
            return {"repo_ids": [42], "hits": 1}

        def fake_metrics(
            *,
            metric_date: str,
            repo_ids: list,
            corroborated_repo_ids: set | None = None,
            db: Any,
        ) -> dict[str, Any]:
            metrics_calls.append(
                {
                    "metric_date": metric_date,
                    "repo_ids": repo_ids,
                    "corroborated_repo_ids": corroborated_repo_ids,
                    "db": db,
                }
            )
            return {"rows": 1, "trending_fallback": 0}

        with (
            patch(
                "backend.app.services.ingestion.github_hot_service.record_github_trending_hits",
                fake_record,
            ),
            patch(
                "backend.app.services.ingestion.github_project_metrics_service.compute_github_daily_metrics",
                fake_metrics,
            ),
        ):
            result = await runtime.run_single_source("github")

        assert result == {"github": 2, "ingested_total": 2}
        assert [c["period"] for c in record_calls] == ["daily", "weekly"]
        assert all(c["db"] is host.github_ingestion for c in record_calls)
        # metrics 仅在 daily 且 repo_ids 非空时触发
        assert metrics_calls == [
            {
                "metric_date": "2024-03-02",
                "repo_ids": [42],
                "corroborated_repo_ids": None,
                "db": host.github_ingestion,
            }
        ]

    async def test_arxiv_collects_only_papers_with_arxiv_id_for_pdf(self) -> None:
        daily_items = [{"arxiv_id": "2403.1", "title": "A"}, {"title": "no id"}]
        weekly_items = [{"arxiv_id": "2403.2", "title": "B"}]
        crawler = FakeCrawler(
            "arxiv",
            ["daily", "weekly"],
            {
                "daily": _result("arxiv", "daily", daily_items),
                "weekly": _result("arxiv", "weekly", weekly_items),
            },
        )
        host = FakeHost({"arxiv": crawler})
        runtime = MultiSourceIngestionRuntime(host)

        result = await runtime.run_single_source("arxiv")

        assert result == {"arxiv": 3, "ingested_total": 3}
        assert len(host.pdf_started) == 1
        assert [p["arxiv_id"] for p in host.pdf_started[0]] == ["2403.1", "2403.2"]

    async def test_fetch_exception_finishes_failed_and_reraises(self) -> None:
        crawler = FakeCrawler("news", ["daily"], raise_exc=RuntimeError("fetch boom"))
        host = FakeHost({"news": crawler})
        runtime = MultiSourceIngestionRuntime(host)

        with self.assertRaises(RuntimeError):
            await runtime.run_single_source("news")

        assert host.finished == [
            {"task_id": 1, "status": "failed", "error_msg": "fetch boom", "item_count": 0}
        ]
        assert host.cache_cleared == 0

    async def test_cache_clear_failure_is_tolerated(self) -> None:
        crawler = FakeCrawler("news", ["daily"], {"daily": _result("news", "daily", [{"title": "A"}])})
        host = FakeHost({"news": crawler}, fail_cache_clear=True)
        runtime = MultiSourceIngestionRuntime(host)

        result = await runtime.run_single_source("news")

        assert result == {"news": 1, "ingested_total": 1}
        assert host.finished[0]["status"] == "success"

    async def test_all_periods_failed_finishes_failed_not_success(self) -> None:
        """单源所有支持周期均采集失败：任务必须记 failed，不得记 success+0。"""
        crawler = FakeCrawler(
            "news",
            ["daily", "weekly", "monthly"],
            {
                "daily": _result("news", "daily", error="boom-daily"),
                "weekly": _result("news", "weekly", error="boom-weekly"),
                "monthly": _result("news", "monthly", error="boom-monthly"),
            },
        )
        host = FakeHost({"news": crawler})
        runtime = MultiSourceIngestionRuntime(host)

        result = await runtime.run_single_source("news")

        assert result == {"news": 0, "ingested_total": 0}
        assert len(host.finished) == 1
        finished = host.finished[0]
        assert finished["status"] == "failed"
        assert finished["item_count"] == 0
        assert "boom-daily" in finished["error_msg"]
        assert "boom-monthly" in finished["error_msg"]
        assert host.cache_cleared == 0  # 零入库不触发缓存清理
        assert host.enriched == []

    async def test_error_plus_empty_periods_without_ingest_finishes_failed(self) -> None:
        """部分周期失败、其余周期空数据且零入库：同样记 failed。"""
        crawler = FakeCrawler(
            "news",
            ["daily", "weekly"],
            {
                "daily": _result("news", "daily", error="boom-daily"),
                "weekly": _result("news", "weekly", []),
            },
        )
        host = FakeHost({"news": crawler})
        runtime = MultiSourceIngestionRuntime(host)

        result = await runtime.run_single_source("news")

        assert result == {"news": 0, "ingested_total": 0}
        assert host.finished[0]["status"] == "failed"
        assert "boom-daily" in host.finished[0]["error_msg"]

    async def test_empty_periods_without_errors_stay_success(self) -> None:
        """全部周期正常但无数据（无任何错误）：保持 success 口径不变。"""
        crawler = FakeCrawler("news", ["daily", "weekly"])
        host = FakeHost({"news": crawler})
        runtime = MultiSourceIngestionRuntime(host)

        result = await runtime.run_single_source("news")

        assert result == {"news": 0, "ingested_total": 0}
        assert host.finished[0] == {
            "task_id": 1,
            "status": "success",
            "error_msg": None,
            "item_count": 0,
        }


class TestRunAll(unittest.IsolatedAsyncioTestCase):
    def _build_host(self, *, target_date: str | None = None, fail_enrich: bool = False) -> FakeHost:
        crawlers = {
            "arxiv": FakeCrawler(
                "arxiv", ["daily"], {"daily": _result("arxiv", "daily", [{"arxiv_id": "2403.1"}])}
            ),
            "news": FakeCrawler(
                "news", ["daily"], {"daily": _result("news", "daily", [{"title": "N1"}, {"title": "N2"}])}
            ),
            "broken": FakeCrawler("broken", ["daily"], raise_exc=RuntimeError("crawl down")),
        }
        return FakeHost(crawlers, target_date=target_date, fail_enrich=fail_enrich)

    async def test_gathers_per_period_and_tolerates_crawl_exceptions(self) -> None:
        host = self._build_host()
        runtime = MultiSourceIngestionRuntime(host)

        stats = await runtime.run_all()

        assert stats == {"arxiv": 1, "news": 2, "broken": 0, "huggingface": 0, "ingested_total": 3}
        assert host.created_tasks == ["multi_source_ingest"]
        assert host.finished == [{"task_id": 1, "status": "success", "error_msg": None, "item_count": 3}]
        assert host.cache_cleared == 1
        # arxiv PDF 后台任务在全部周期结束后触发一次
        assert len(host.pdf_started) == 1
        assert [p["arxiv_id"] for p in host.pdf_started[0]] == ["2403.1"]
        # broken 的异常被 gather 隔离，不影响其他源 enrich
        assert {e["source_name"] for e in host.enriched} == {"arxiv", "news"}

    async def test_task_name_uses_target_date_when_set(self) -> None:
        host = self._build_host(target_date="2024-03-02")
        runtime = MultiSourceIngestionRuntime(host)

        await runtime.run_all()

        assert host.created_tasks == ["date_ingest:2024-03-02"]
        arxiv_crawler = host._crawlers["arxiv"]
        assert arxiv_crawler.fetch_calls[0]["target_date"] == "2024-03-02"

    async def test_enrich_failure_finishes_failed_and_reraises(self) -> None:
        host = self._build_host(fail_enrich=True)
        runtime = MultiSourceIngestionRuntime(host)

        with self.assertRaises(RuntimeError):
            await runtime.run_all()

        assert host.finished == [
            {"task_id": 1, "status": "failed", "error_msg": "enrich down", "item_count": 0}
        ]
        assert host.pdf_started == []

    async def test_all_sources_failed_finishes_failed_not_success(self) -> None:
        """全源整轮零入库且存在采集错误：任务记 failed 而非 success+0。"""
        crawlers = {
            "broken_a": FakeCrawler(
                "broken_a",
                ["daily"],
                {"daily": _result("broken_a", "daily", error="down-a")},
            ),
            "broken_b": FakeCrawler("broken_b", ["daily"], raise_exc=RuntimeError("crawl down")),
        }
        host = FakeHost(crawlers)
        runtime = MultiSourceIngestionRuntime(host)

        stats = await runtime.run_all()

        assert stats["ingested_total"] == 0
        assert len(host.finished) == 1
        finished = host.finished[0]
        assert finished["status"] == "failed"
        assert finished["item_count"] == 0
        assert "down-a" in finished["error_msg"]
        assert host.cache_cleared == 0
        assert host.pdf_started == []

    async def test_partial_source_failure_with_ingest_stays_success(self) -> None:
        """个别源失败但有入库：保持 success 口径（行为兼容）。"""
        host = self._build_host()  # broken 源抛异常，但 arxiv/news 正常入库
        runtime = MultiSourceIngestionRuntime(host)

        stats = await runtime.run_all()

        assert stats["ingested_total"] == 3
        assert host.finished[0]["status"] == "success"
