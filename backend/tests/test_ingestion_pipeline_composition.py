from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.services.ingestion.pipeline import (
    IngestionOrchestrator,
    run_ingestion_pipeline,
    run_ingestion_pipeline_async,
    run_single_source_async,
    run_single_source_pipeline,
)


class IngestionPublicEntrypointTests(unittest.IsolatedAsyncioTestCase):
    def test_sync_full_entrypoint_delegates_parameters_and_run_all(self) -> None:
        orchestrator = MagicMock()
        pending = object()
        orchestrator.run_all.return_value = pending

        with (
            patch(
                "backend.app.services.ingestion.pipeline.IngestionOrchestrator",
                return_value=orchestrator,
            ) as factory,
            patch(
                "backend.app.services.ingestion.pipeline.asyncio.run",
                return_value={"ingested_total": 3},
            ) as run,
        ):
            result = run_ingestion_pipeline(limit=7, top_n=4, target_date="2026-07-25")

        factory.assert_called_once_with(limit=7, top_n=4, target_date="2026-07-25")
        orchestrator.run_all.assert_called_once_with()
        run.assert_called_once_with(pending)
        self.assertEqual(result, {"ingested_total": 3})

    def test_sync_single_entrypoint_delegates_periods(self) -> None:
        orchestrator = MagicMock()
        pending = object()
        orchestrator.run_single_source.return_value = pending

        with (
            patch(
                "backend.app.services.ingestion.pipeline.IngestionOrchestrator",
                return_value=orchestrator,
            ) as factory,
            patch(
                "backend.app.services.ingestion.pipeline.asyncio.run",
                return_value={"news": 2, "ingested_total": 2},
            ) as run,
        ):
            result = run_single_source_pipeline(
                "news",
                limit=8,
                top_n=5,
                target_date="2026-07-25",
                periods=["weekly", "daily"],
            )

        factory.assert_called_once_with(limit=8, top_n=5, target_date="2026-07-25")
        orchestrator.run_single_source.assert_called_once_with(
            "news", periods=["weekly", "daily"]
        )
        run.assert_called_once_with(pending)
        self.assertEqual(result, {"news": 2, "ingested_total": 2})

    async def test_async_full_entrypoint_delegates_to_run_all(self) -> None:
        orchestrator = MagicMock()
        orchestrator.run_all = AsyncMock(return_value={"ingested_total": 1})

        with patch(
            "backend.app.services.ingestion.pipeline.IngestionOrchestrator",
            return_value=orchestrator,
        ) as factory:
            result = await run_ingestion_pipeline_async(
                limit=9, top_n=6, target_date="2026-07-25"
            )

        factory.assert_called_once_with(limit=9, top_n=6, target_date="2026-07-25")
        orchestrator.run_all.assert_awaited_once_with()
        self.assertEqual(result, {"ingested_total": 1})

    async def test_async_single_entrypoint_delegates_to_run_single_source(self) -> None:
        orchestrator = MagicMock()
        orchestrator.run_single_source = AsyncMock(
            return_value={"arxiv": 1, "ingested_total": 1}
        )

        with patch(
            "backend.app.services.ingestion.pipeline.IngestionOrchestrator",
            return_value=orchestrator,
        ) as factory:
            result = await run_single_source_async(
                "arxiv", limit=10, top_n=7, target_date="2026-07-25"
            )

        factory.assert_called_once_with(limit=10, top_n=7, target_date="2026-07-25")
        orchestrator.run_single_source.assert_awaited_once_with("arxiv")
        self.assertEqual(result, {"arxiv": 1, "ingested_total": 1})


class ArxivPdfBackgroundTests(unittest.TestCase):
    @staticmethod
    def _orchestrator() -> IngestionOrchestrator:
        orchestrator = IngestionOrchestrator.__new__(IngestionOrchestrator)
        orchestrator.documents = MagicMock()
        return orchestrator

    def test_background_is_daemon_nonblocking_and_filters_pdf_candidates(self) -> None:
        orchestrator = self._orchestrator()
        captured: dict[str, object] = {}

        class FakeThread:
            def __init__(self, *, target, name, daemon):
                captured.update(target=target, name=name, daemon=daemon)

            def start(self) -> None:
                captured["started"] = True

        papers = [
            {"arxiv_id": "2607.1", "pdf_url": "https://arxiv/1.pdf"},
            {"arxiv_id": "2607.2"},
            {"pdf_url": "https://arxiv/3.pdf"},
        ]
        with (
            patch("backend.app.services.ingestion.pipeline.threading.Thread", FakeThread),
            patch("backend.app.services.ingestion.pipeline.download_and_index_arxiv_pdfs") as download,
        ):
            orchestrator._start_arxiv_pdf_background(papers)

        self.assertEqual(captured["name"], "arxiv-pdf-download")
        self.assertIs(captured["daemon"], True)
        self.assertIs(captured["started"], True)
        download.assert_not_called()

    def test_background_passes_fixed_download_parameters(self) -> None:
        orchestrator = self._orchestrator()
        paper = {"arxiv_id": "2607.1", "pdf_url": "https://arxiv/1.pdf"}
        vector_writer = MagicMock()

        class ImmediateThread:
            def __init__(self, *, target, **_):
                self.target = target

            def start(self) -> None:
                self.target()

        with (
            patch("backend.app.services.ingestion.pipeline.threading.Thread", ImmediateThread),
            patch(
                "backend.app.services.ingestion.pipeline.MilvusRepository",
                return_value=vector_writer,
            ),
            patch(
                "backend.app.services.ingestion.pipeline.download_and_index_arxiv_pdfs",
                return_value=(1, 1),
            ) as download,
        ):
            orchestrator._start_arxiv_pdf_background([paper])

        download.assert_called_once_with(
            [paper],
            milvus_repo=vector_writer,
            mysql_repo=orchestrator.documents,
            sleep_between=3.0,
            max_workers=1,
        )

    def test_background_worker_isolates_factory_and_download_errors(self) -> None:
        orchestrator = self._orchestrator()
        paper = {"arxiv_id": "2607.1", "pdf_url": "https://arxiv/1.pdf"}

        class ImmediateThread:
            def __init__(self, *, target, **_):
                self.target = target

            def start(self) -> None:
                self.target()

        failures = (
            (
                MagicMock(side_effect=RuntimeError("factory failed")),
                MagicMock(return_value=(0, 0)),
            ),
            (MagicMock(), MagicMock(side_effect=RuntimeError("download failed"))),
        )
        for vector_factory, download in failures:
            with self.subTest(download_fails=bool(download.side_effect)), patch(
                "backend.app.services.ingestion.pipeline.threading.Thread", ImmediateThread
            ), patch(
                "backend.app.services.ingestion.pipeline.MilvusRepository",
                new=vector_factory,
            ), patch(
                "backend.app.services.ingestion.pipeline.download_and_index_arxiv_pdfs",
                new=download,
            ):
                orchestrator._start_arxiv_pdf_background([paper])


if __name__ == "__main__":
    unittest.main()
