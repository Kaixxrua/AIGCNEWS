from __future__ import annotations

import ast
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.services.ingestion.composition import (
    IngestionDependencies,
    provide_ingestion_dependencies,
)
from backend.app.services.ingestion.pipeline import (
    IngestionOrchestrator,
    run_ingestion_pipeline,
    run_ingestion_pipeline_async,
    run_single_source_async,
    run_single_source_pipeline,
)


class IngestionDependencyCompositionTests(unittest.TestCase):
    def test_provider_borrows_repositories_and_exposes_owned_factories(self) -> None:
        repositories = MagicMock()
        writer = MagicMock()

        dependencies = provide_ingestion_dependencies(
            repositories=repositories,
            task_writer=writer,
        )

        self.assertIs(dependencies.repositories, repositories)
        self.assertIs(dependencies.task_writer, writer)
        self.assertTrue(callable(dependencies.vector_writer_factory))
        self.assertTrue(callable(dependencies.graph_extractor_factory))
        self.assertTrue(callable(dependencies.graph_writer_factory))
        self.assertTrue(callable(dependencies.pdf_vector_writer_factory))
        self.assertTrue(callable(dependencies.pdf_indexer))
        self.assertTrue(callable(dependencies.cache_invalidator))
        self.assertEqual(len(dependencies.crawler_factories), 7)

    def test_x_crawler_factory_reads_watchlist_from_repositories(self) -> None:
        repositories = MagicMock()

        dependencies = provide_ingestion_dependencies(
            repositories=repositories,
            task_writer=MagicMock(),
        )
        x_crawler = dependencies.crawler_factories[-1]()

        self.assertIs(
            x_crawler._watchlist_provider,
            repositories.x_watch_accounts.list_enabled_x_handles,
        )

    def test_orchestrator_accepts_complete_composition_without_global_lookup(self) -> None:
        repositories = MagicMock()
        dependencies = IngestionDependencies(
            repositories=repositories,
            task_writer=repositories.ingestion_tasks,
            vector_writer_factory=MagicMock(),
            graph_extractor_factory=MagicMock(),
            graph_writer_factory=MagicMock(),
            pdf_vector_writer_factory=MagicMock(),
            pdf_indexer=MagicMock(),
            cache_invalidator=AsyncMock(),
            crawler_factories=(),
        )

        orchestrator = IngestionOrchestrator(dependencies=dependencies)

        self.assertIs(orchestrator.dependencies, dependencies)
        self.assertIs(orchestrator.repositories, repositories)
        self.assertIs(orchestrator.documents, repositories.documents)
        self.assertIs(orchestrator.task_writer, repositories.ingestion_tasks)


class IngestionPublicEntrypointTests(unittest.IsolatedAsyncioTestCase):
    def test_sync_full_entrypoint_provides_dependencies_and_delegates_parameters(self) -> None:
        dependencies = MagicMock()
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
            result = run_ingestion_pipeline(
                limit=7,
                top_n=4,
                target_date="2026-07-25",
                dependencies=dependencies,
            )

        factory.assert_called_once_with(
            limit=7,
            top_n=4,
            target_date="2026-07-25",
            dependencies=dependencies,
        )
        orchestrator.run_all.assert_called_once_with()
        run.assert_called_once_with(pending)
        self.assertEqual(result, {"ingested_total": 3})

    def test_sync_single_entrypoint_delegates_periods(self) -> None:
        dependencies = MagicMock()
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
                dependencies=dependencies,
            )

        factory.assert_called_once_with(
            limit=8,
            top_n=5,
            target_date="2026-07-25",
            dependencies=dependencies,
        )
        orchestrator.run_single_source.assert_called_once_with(
            "news", periods=["weekly", "daily"]
        )
        run.assert_called_once_with(pending)
        self.assertEqual(result, {"news": 2, "ingested_total": 2})

    async def test_async_full_entrypoint_delegates_to_run_all(self) -> None:
        dependencies = MagicMock()
        orchestrator = MagicMock()
        orchestrator.run_all = AsyncMock(return_value={"ingested_total": 1})

        with patch(
            "backend.app.services.ingestion.pipeline.IngestionOrchestrator",
            return_value=orchestrator,
        ) as factory:
            result = await run_ingestion_pipeline_async(
                limit=9,
                top_n=6,
                target_date="2026-07-25",
                dependencies=dependencies,
            )

        factory.assert_called_once_with(
            limit=9,
            top_n=6,
            target_date="2026-07-25",
            dependencies=dependencies,
        )
        orchestrator.run_all.assert_awaited_once_with()
        self.assertEqual(result, {"ingested_total": 1})

    async def test_async_single_entrypoint_delegates_to_run_single_source(self) -> None:
        dependencies = MagicMock()
        orchestrator = MagicMock()
        orchestrator.run_single_source = AsyncMock(
            return_value={"arxiv": 1, "ingested_total": 1}
        )

        with patch(
            "backend.app.services.ingestion.pipeline.IngestionOrchestrator",
            return_value=orchestrator,
        ) as factory:
            result = await run_single_source_async(
                "arxiv",
                limit=10,
                top_n=7,
                target_date="2026-07-25",
                dependencies=dependencies,
            )

        factory.assert_called_once_with(
            limit=10,
            top_n=7,
            target_date="2026-07-25",
            dependencies=dependencies,
        )
        orchestrator.run_single_source.assert_awaited_once_with("arxiv")
        self.assertEqual(result, {"arxiv": 1, "ingested_total": 1})

    def test_public_entrypoints_require_explicit_dependencies(self) -> None:
        with self.assertRaises(TypeError):
            run_ingestion_pipeline(limit=7)
        with self.assertRaises(TypeError):
            run_single_source_pipeline("news", limit=8)

    async def test_async_entrypoints_require_explicit_dependencies(self) -> None:
        with self.assertRaises(TypeError):
            await run_ingestion_pipeline_async(limit=9)
        with self.assertRaises(TypeError):
            await run_single_source_async("arxiv", limit=10)


class IngestionCompositionArchitectureTests(unittest.TestCase):
    def test_public_entrypoints_construct_orchestrators_through_composition_helper(self) -> None:
        pipeline_path = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "ingestion"
            / "pipeline.py"
        )
        module = ast.parse(
            pipeline_path.read_text(encoding="utf-8"),
            filename=str(pipeline_path),
        )
        functions = {
            node.name: node
            for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }

        for name in (
            "run_ingestion_pipeline",
            "run_single_source_pipeline",
            "run_ingestion_pipeline_async",
            "run_single_source_async",
        ):
            with self.subTest(entrypoint=name):
                called_names = {
                    node.func.id
                    for node in ast.walk(functions[name])
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                }
                self.assertNotIn("IngestionOrchestrator", called_names)
                self.assertTrue(
                    {"_compose_ingestion_orchestrator", "_run_ingestion_pipeline_with_dependencies"}
                    & called_names
                )

        composed_calls = [
            node
            for node in ast.walk(functions["_compose_ingestion_orchestrator"])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "IngestionOrchestrator"
        ]
        self.assertEqual(len(composed_calls), 1)
        self.assertIn(
            "dependencies",
            {keyword.arg for keyword in composed_calls[0].keywords},
        )

    def test_run_ingestion_script_uses_current_async_facade_signature(self) -> None:
        script_path = Path(__file__).resolve().parents[2] / "run_ingestion.py"
        module = ast.parse(
            script_path.read_text(encoding="utf-8"),
            filename=str(script_path),
        )
        calls = [
            node
            for node in ast.walk(module)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "run_ingestion_pipeline_async"
        ]
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            {keyword.arg for keyword in calls[0].keywords},
            {"limit", "dependencies"},
        )

    def test_pipeline_does_not_construct_concrete_dependencies_or_read_process_context(self) -> None:
        pipeline_path = (
            Path(__file__).resolve().parents[1]
            / "app"
            / "services"
            / "ingestion"
            / "pipeline.py"
        )
        module = ast.parse(
            pipeline_path.read_text(encoding="utf-8"),
            filename=str(pipeline_path),
        )
        forbidden_calls = {
            "ArxivCrawler",
            "GitHubCrawler",
            "NewsCrawler",
            "ProductHuntCrawler",
            "HackerNewsCrawler",
            "MilvusRepository",
            "GraphExtractor",
            "GraphRepository",
            "get_configured_application_repositories",
        }
        called_names = {
            node.func.id
            for node in ast.walk(module)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertEqual(called_names & forbidden_calls, set())


class ArxivPdfBackgroundTests(unittest.TestCase):
    @staticmethod
    def _orchestrator() -> IngestionOrchestrator:
        repositories = MagicMock()
        dependencies = IngestionDependencies(
            repositories=repositories,
            task_writer=repositories.ingestion_tasks,
            vector_writer_factory=MagicMock(),
            graph_extractor_factory=MagicMock(),
            graph_writer_factory=MagicMock(),
            pdf_vector_writer_factory=MagicMock(),
            pdf_indexer=MagicMock(),
            cache_invalidator=AsyncMock(),
            crawler_factories=(),
        )
        return IngestionOrchestrator(dependencies)

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
        with patch(
            "backend.app.services.ingestion.pipeline.threading.Thread", FakeThread
        ):
            orchestrator._start_arxiv_pdf_background(papers)

        self.assertEqual(captured["name"], "arxiv-pdf-download")
        self.assertIs(captured["daemon"], True)
        self.assertIs(captured["started"], True)
        orchestrator.dependencies.pdf_indexer.assert_not_called()

    def test_background_passes_fixed_download_parameters(self) -> None:
        orchestrator = self._orchestrator()
        paper = {"arxiv_id": "2607.1", "pdf_url": "https://arxiv/1.pdf"}
        vector_writer = MagicMock()

        class ImmediateThread:
            def __init__(self, *, target, **_):
                self.target = target

            def start(self) -> None:
                self.target()

        orchestrator.dependencies.pdf_vector_writer_factory.return_value = vector_writer
        orchestrator.dependencies.pdf_indexer.return_value = (1, 1)
        with patch(
            "backend.app.services.ingestion.pipeline.threading.Thread", ImmediateThread
        ):
            orchestrator._start_arxiv_pdf_background([paper])

        orchestrator.dependencies.pdf_indexer.assert_called_once_with(
            [paper],
            milvus_repo=vector_writer,
            document_writer=orchestrator.documents,
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
            orchestrator.dependencies = replace(
                orchestrator.dependencies,
                pdf_vector_writer_factory=vector_factory,
                pdf_indexer=download,
            )
            with self.subTest(download_fails=bool(download.side_effect)), patch(
                "backend.app.services.ingestion.pipeline.threading.Thread", ImmediateThread
            ):
                orchestrator._start_arxiv_pdf_background([paper])


if __name__ == "__main__":
    unittest.main()
