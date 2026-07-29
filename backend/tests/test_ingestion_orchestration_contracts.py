from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, call, patch

from backend.app.services.ingestion.base_crawler import CrawlResult
from backend.app.services.ingestion.pipeline import IngestionOrchestrator


class _Crawler:
    def __init__(self, source: str, periods: list[str], results: dict[str, CrawlResult]):
        self.source_name = source
        self.supported_periods = periods
        self._results = results
        self.fetch = AsyncMock(side_effect=lambda *, period, **_: self._results[period])


def _result(source: str, period: str, items: list[dict], date: str = "2026-07-24") -> CrawlResult:
    return CrawlResult(
        source=source,
        source_channel=f"{source}_{period}",
        snapshot_date=date,
        period=period,
        items=items,
    )


class IngestionOrchestrationContractTests(unittest.IsolatedAsyncioTestCase):
    def _orchestrator(self, crawlers: dict[str, _Crawler]) -> IngestionOrchestrator:
        orchestrator = IngestionOrchestrator.__new__(IngestionOrchestrator)
        orchestrator.limit = 25
        orchestrator.top_n = 10
        orchestrator.target_date = None
        orchestrator.snapshot_date = "2026-07-24"
        orchestrator.documents = MagicMock()
        orchestrator.rank_snapshots = MagicMock()
        orchestrator.github_ingestion = MagicMock()
        orchestrator.task_writer = MagicMock()
        orchestrator.task_writer.create_task.return_value = 42
        orchestrator._cache_invalidator = AsyncMock()
        orchestrator._crawlers = crawlers
        orchestrator._enrich_and_ingest = AsyncMock(side_effect=lambda **kwargs: len(kwargs["papers"]))
        orchestrator._start_arxiv_pdf_background = MagicMock()
        return orchestrator

    async def test_run_all_preserves_period_gathers_source_order_and_period_flags(self) -> None:
        events: list[tuple[str, str]] = []

        def crawler(source: str) -> _Crawler:
            results = {
                period: _result(
                    source,
                    period,
                    [{"source": source, "title": f"{source}-{period}"}],
                    date=f"2026-07-{day}",
                )
                for period, day in (("daily", "24"), ("weekly", "23"), ("monthly", "22"))
            }
            instance = _Crawler(source, ["daily", "weekly", "monthly"], results)

            async def fetch(*, period: str, **_: object) -> CrawlResult:
                events.append(("fetch", f"{period}:{source}"))
                await asyncio.sleep(0)
                return results[period]

            instance.fetch = AsyncMock(side_effect=fetch)
            return instance

        arxiv = crawler("arxiv")
        news = crawler("news")
        orchestrator = self._orchestrator({"arxiv": arxiv, "news": news})

        async def ingest(**kwargs: object) -> int:
            events.append(("ingest", str(kwargs["log_label"])))
            return 1

        orchestrator._enrich_and_ingest = AsyncMock(side_effect=ingest)
        with patch.object(
            orchestrator,
            "_cache_invalidator",
            new=AsyncMock(),
        ):
            result = await orchestrator.run_all()

        self.assertEqual(
            [label for kind, label in events if kind == "ingest"],
            [
                "arxiv_daily",
                "news_daily",
                "arxiv_weekly",
                "news_weekly",
                "arxiv_monthly",
                "news_monthly",
            ],
        )
        for period in ("daily", "weekly", "monthly"):
            fetch_indexes = [
                index
                for index, event in enumerate(events)
                if event in (("fetch", f"{period}:arxiv"), ("fetch", f"{period}:news"))
            ]
            first_ingest = events.index(("ingest", f"arxiv_{period}"))
            self.assertTrue(all(index < first_ingest for index in fetch_indexes))
        for invocation in orchestrator._enrich_and_ingest.await_args_list:
            period = invocation.kwargs["log_label"].rsplit("_", 1)[1]
            paper = invocation.kwargs["papers"][0]
            self.assertEqual(paper["in_daily"], int(period == "daily"))
            self.assertEqual(paper["in_weekly"], int(period == "weekly"))
            self.assertEqual(paper["in_monthly"], int(period == "monthly"))
            self.assertEqual(invocation.kwargs["snapshot_date"], {
                "daily": "2026-07-24",
                "weekly": "2026-07-23",
                "monthly": "2026-07-22",
            }[period])
        self.assertEqual(result, {"arxiv": 3, "news": 3, "huggingface": 0, "ingested_total": 6})
        orchestrator.task_writer.finish_task.assert_called_once_with(
            42, status="success", error_msg=None, item_count=6
        )
        pdf_papers = orchestrator._start_arxiv_pdf_background.call_args.args[0]
        self.assertEqual([paper["title"] for paper in pdf_papers], [])

    async def test_run_all_finishes_task_before_cache_and_starts_pdf_after_cache(self) -> None:
        paper = {"source": "arxiv", "title": "Paper", "arxiv_id": "2607.1"}
        crawler = _Crawler("arxiv", ["daily"], {"daily": _result("arxiv", "daily", [paper])})
        orchestrator = self._orchestrator({"arxiv": crawler})
        events: list[str] = []
        orchestrator.task_writer.finish_task.side_effect = lambda *args, **kwargs: events.append("finish")
        orchestrator._start_arxiv_pdf_background.side_effect = lambda papers: events.append("pdf")

        async def clear_cache() -> None:
            events.append("cache")

        with patch.object(
            orchestrator,
            "_cache_invalidator",
            new=AsyncMock(side_effect=clear_cache),
        ):
            await orchestrator.run_all()

        self.assertEqual(events, ["finish", "cache", "pdf"])
        orchestrator._start_arxiv_pdf_background.assert_called_once_with([paper])

    async def test_run_all_continues_after_fetch_exception_and_failed_result(self) -> None:
        exception_source = _Crawler("news", ["daily"], {})
        exception_source.fetch = AsyncMock(side_effect=RuntimeError("crawl failed"))
        failed_result_source = _Crawler(
            "producthunt",
            ["daily"],
            {
                "daily": CrawlResult(
                    source="producthunt",
                    source_channel="producthunt_daily",
                    snapshot_date="2026-07-24",
                    period="daily",
                    error="upstream rejected request",
                )
            },
        )
        good = _Crawler(
            "arxiv",
            ["daily"],
            {"daily": _result("arxiv", "daily", [{"title": "Paper"}])},
        )
        orchestrator = self._orchestrator(
            {
                "news": exception_source,
                "producthunt": failed_result_source,
                "arxiv": good,
            }
        )

        with patch.object(
            orchestrator,
            "_cache_invalidator",
            new=AsyncMock(),
        ):
            result = await orchestrator.run_all()

        self.assertEqual(result["news"], 0)
        self.assertEqual(result["producthunt"], 0)
        self.assertEqual(result["arxiv"], 1)
        orchestrator._enrich_and_ingest.assert_awaited_once()
        orchestrator.task_writer.finish_task.assert_called_once_with(
            42, status="success", error_msg=None, item_count=1
        )

    async def test_run_all_primary_persistence_failure_is_fail_closed(self) -> None:
        crawler = _Crawler(
            "news",
            ["daily"],
            {"daily": _result("news", "daily", [{"title": "Item"}])},
        )
        orchestrator = self._orchestrator({"news": crawler})
        error = RuntimeError("document persistence failed")
        orchestrator._enrich_and_ingest = AsyncMock(side_effect=error)

        with self.assertRaises(RuntimeError) as context:
            await orchestrator.run_all()

        self.assertIs(context.exception, error)
        orchestrator.task_writer.finish_task.assert_called_once_with(
            42,
            status="failed",
            error_msg="document persistence failed",
            item_count=0,
        )
        orchestrator._start_arxiv_pdf_background.assert_not_called()

    async def test_cache_clear_failure_is_nonfatal_after_successful_persistence(self) -> None:
        crawler = _Crawler(
            "news",
            ["daily"],
            {"daily": _result("news", "daily", [{"title": "Item"}])},
        )
        orchestrator = self._orchestrator({"news": crawler})

        with patch.object(
            orchestrator,
            "_cache_invalidator",
            new=AsyncMock(side_effect=RuntimeError("redis unavailable")),
        ):
            result = await orchestrator.run_all()

        self.assertEqual(result, {"news": 1, "huggingface": 0, "ingested_total": 1})
        orchestrator.task_writer.finish_task.assert_called_once_with(
            42, status="success", error_msg=None, item_count=1
        )
        orchestrator._start_arxiv_pdf_background.assert_called_once_with([])

    async def test_run_single_source_preserves_requested_period_order_and_github_timing(self) -> None:
        daily = _result("github", "daily", [{"title": "Daily"}], "2026-07-24")
        weekly = _result("github", "weekly", [{"title": "Weekly"}], "2026-07-20")
        crawler = _Crawler("github", ["daily", "weekly"], {"daily": daily, "weekly": weekly})
        orchestrator = self._orchestrator({"github": crawler})
        events: list[str] = []

        async def to_thread(function, *args, **kwargs):
            if function.__name__ == "record_github_trending_hits":
                events.append(f"hits:{kwargs['period']}")
                return {"repo_ids": [7], "hits": 1}
            events.append("metrics")
            return {"rows": 1, "trending_fallback": 0}

        async def ingest(**kwargs: object) -> int:
            events.append(f"ingest:{kwargs['log_label']}")
            return 1

        orchestrator._enrich_and_ingest = AsyncMock(side_effect=ingest)
        with (
            patch(
                "backend.app.services.ingestion.pipeline.asyncio.to_thread",
                new=AsyncMock(side_effect=to_thread),
            ) as pipeline_to_thread,
            patch.object(
                orchestrator,
                "_cache_invalidator",
                new=AsyncMock(),
            ),
        ):
            result = await orchestrator.run_single_source("github", ["weekly", "daily"])

        self.assertEqual(events, ["hits:weekly", "ingest:github_weekly", "hits:daily", "metrics", "ingest:github_daily"])
        to_thread_mock = pipeline_to_thread
        self.assertTrue(
            all(
                call_item.kwargs.get("db") is orchestrator.github_ingestion
                for call_item in to_thread_mock.await_args_list
                if call_item.args[0].__name__
                in {"record_github_trending_hits", "compute_github_daily_metrics"}
            )
        )
        self.assertEqual(result, {"github": 2, "ingested_total": 2})
        crawler.fetch.assert_has_awaits(
            [
                call(period="weekly", limit=25, target_date=None),
                call(period="daily", limit=25, target_date=None),
            ]
        )

    async def test_run_single_source_failure_finishes_with_zero_and_propagates_same_error(self) -> None:
        crawler = _Crawler(
            "news",
            ["daily"],
            {"daily": _result("news", "daily", [{"title": "Item"}])},
        )
        orchestrator = self._orchestrator({"news": crawler})
        error = RuntimeError("ingest failed")
        orchestrator._enrich_and_ingest = AsyncMock(side_effect=error)

        with self.assertRaises(RuntimeError) as context:
            await orchestrator.run_single_source("news", ["daily"])

        self.assertIs(context.exception, error)
        orchestrator.task_writer.finish_task.assert_called_once_with(
            42, status="failed", error_msg="ingest failed", item_count=0
        )

    async def test_run_single_source_starts_arxiv_pdf_before_task_finish(self) -> None:
        paper = {"source": "arxiv", "title": "Paper", "arxiv_id": "2607.1"}
        crawler = _Crawler("arxiv", ["daily"], {"daily": _result("arxiv", "daily", [paper])})
        orchestrator = self._orchestrator({"arxiv": crawler})
        events: list[str] = []
        orchestrator._start_arxiv_pdf_background.side_effect = lambda papers: events.append("pdf")
        orchestrator.task_writer.finish_task.side_effect = lambda *args, **kwargs: events.append("finish")

        with patch.object(
            orchestrator,
            "_cache_invalidator",
            new=AsyncMock(side_effect=lambda: events.append("cache")),
        ):
            await orchestrator.run_single_source("arxiv", ["daily"])

        self.assertEqual(events, ["pdf", "finish", "cache"])
        orchestrator._start_arxiv_pdf_background.assert_called_once_with([paper])


if __name__ == "__main__":
    unittest.main()
