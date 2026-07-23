from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

config = types.ModuleType("backend.app.core.config")
config.settings = MagicMock()
sys.modules.setdefault("backend.app.core.config", config)

from backend.app.core import scheduler
from backend.app.services.ingestion.crawlers.arxiv_crawler import ArxivCrawler

try:
    from backend.app.services.ingestion.pipeline import IngestionOrchestrator
except ModuleNotFoundError as exc:
    if exc.name not in {"langchain_core", "neo4j", "pymilvus"}:
        raise
    IngestionOrchestrator = None


class SnapshotDateFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_arxiv_crawler_uses_actual_hf_fallback_date(self) -> None:
        papers = [{"title": "paper", "snapshot_date": "2026-07-12"}]
        with patch(
            "backend.app.services.ingestion.crawlers.arxiv_crawler.fetch_latest_papers_async",
            new=AsyncMock(return_value=papers),
        ):
            result = await ArxivCrawler().fetch("daily", target_date=None)

        self.assertEqual(result.snapshot_date, "2026-07-12")
        self.assertEqual(result.items[0]["snapshot_date"], "2026-07-12")

    @unittest.skipIf(IngestionOrchestrator is None, "optional pipeline dependencies unavailable")
    async def test_pipeline_passes_crawl_result_snapshot_date_to_ingest(self) -> None:
        orchestrator = object.__new__(IngestionOrchestrator)
        orchestrator.top_n = 10
        orchestrator.snapshot_date = "2026-07-13"
        orchestrator.db = MagicMock()

        with (
            patch("backend.app.services.ingestion.pipeline._select_top", return_value=[{"title": "paper"}]),
            patch("backend.app.services.ingestion.pipeline._apply_existing_summary_short_circuit", side_effect=lambda papers, *_: papers),
            patch("backend.app.services.ingestion.pipeline.enrich_papers", new=AsyncMock(side_effect=lambda papers, **_: papers)),
            patch("backend.app.services.ingestion.pipeline.asyncio.to_thread", new=AsyncMock(return_value=1)) as to_thread,
        ):
            count = await orchestrator._enrich_and_ingest(
                "arxiv", [{"title": "paper"}], 1, snapshot_date="2026-07-12"
            )

        self.assertEqual(count, 1)
        self.assertEqual(to_thread.call_args.args[5], "2026-07-12")
        self.assertIs(to_thread.call_args.args[7], orchestrator.db.rank_snapshots)

    def test_reconciliation_is_bounded_and_oldest_first(self) -> None:
        snapshots = MagicMock()
        snapshots.get_snapshot_dates.return_value = ["2026-07-13"]
        repo = MagicMock(rank_snapshots=snapshots)
        with (
            patch("backend.app.repositories.mysql_repo.MySQLRepository", return_value=repo),
            patch("backend.app.services.ingestion.base_crawler.today_cst", return_value="2026-07-13"),
        ):
            missing = scheduler._missing_recent_arxiv_daily_dates()

        self.assertEqual(missing, ["2026-07-11", "2026-07-12"])
        snapshots.get_snapshot_dates.assert_called_once_with(
            limit=2, source="arxiv", period="daily"
        )

    async def test_reconciliation_skips_when_date_lookup_fails(self) -> None:
        with patch(
            "backend.app.core.scheduler.asyncio.to_thread",
            new=AsyncMock(side_effect=RuntimeError("database unavailable")),
        ) as to_thread:
            await scheduler._reconcile_recent_arxiv_daily_snapshots()

        to_thread.assert_awaited_once_with(scheduler._missing_recent_arxiv_daily_dates)

    async def test_reconciliation_continues_after_one_date_fails(self) -> None:
        pipeline = types.ModuleType("backend.app.services.ingestion.pipeline")
        pipeline.run_single_source_pipeline = MagicMock()
        with (
            patch(
                "backend.app.core.scheduler._missing_recent_arxiv_daily_dates",
                return_value=["2026-07-11", "2026-07-12"],
            ),
            patch.dict(
                sys.modules,
                {"backend.app.services.ingestion.pipeline": pipeline},
            ),
            patch(
                "backend.app.core.scheduler.asyncio.to_thread",
                new=AsyncMock(side_effect=[["2026-07-11", "2026-07-12"], RuntimeError("crawl failed"), {}]),
            ) as to_thread,
        ):
            await scheduler._reconcile_recent_arxiv_daily_snapshots()

        self.assertEqual(to_thread.await_count, 3)
        self.assertEqual(to_thread.await_args_list[1].args[1], "arxiv")
        self.assertEqual(to_thread.await_args_list[1].kwargs["target_date"], "2026-07-11")
        self.assertEqual(to_thread.await_args_list[2].kwargs["target_date"], "2026-07-12")
        self.assertEqual(to_thread.await_args_list[2].kwargs["periods"], ["daily"])


if __name__ == "__main__":
    unittest.main()
