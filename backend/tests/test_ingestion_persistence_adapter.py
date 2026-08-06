from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.services.ingestion.persistence_adapter import (
    IngestionPersistenceAdapter,
    project_document_write,
)
from backend.app.services.ingestion.task_lifecycle import IngestionTaskLifecycle


class IngestionPersistenceAdapterTests(unittest.TestCase):
    def _adapter(self):
        documents = MagicMock()
        snapshots = MagicMock()
        vectors = MagicMock()
        extractor = MagicMock()
        graph = MagicMock()
        adapter = IngestionPersistenceAdapter(
            documents=documents,
            rank_snapshots=snapshots,
            vector_writer_factory=MagicMock(return_value=vectors),
            graph_extractor_factory=MagicMock(return_value=extractor),
            graph_writer_factory=MagicMock(return_value=graph),
        )
        return adapter, documents, snapshots, vectors, extractor, graph

    def test_document_write_projection_preserves_defaults_and_precedence(self) -> None:
        document = MagicMock(
            metadata={
                "id": "doc-1",
                "stars": 7,
                "language": "Python",
                "ai_score": 8.5,
            }
        )
        paper = {
            "source": "github",
            "channel": "github_daily",
            "title": "Repo",
            "abstract": "x" * 600,
            "score": 12,
            "forks": "3",
            "rank_in_period": 0,
            "in_daily": 1,
        }

        write = project_document_write(paper, document, "github_daily")

        self.assertEqual(write["id"], "doc-1")
        self.assertEqual(write["source_channel"], "github_daily")
        self.assertEqual(write["summary"], "x" * 500)
        self.assertEqual(write["score"], 8.5)
        self.assertEqual(write["raw_score"], 12)
        self.assertEqual(write["forks"], 3)
        self.assertEqual(write["rank_in_period"], 9999)
        self.assertEqual(write["in_daily"], 1)
        self.assertEqual(write["in_weekly"], 0)

    def test_document_write_projection_passes_translation_zh_through(self) -> None:
        document = MagicMock(metadata={"id": "doc-x"})
        paper = {
            "source": "x",
            "channel": "x_daily_watchlist",
            "title": "Tweet",
            "translation_zh": "中文译文",
        }

        write = project_document_write(paper, document, "x")

        self.assertEqual(write["translation_zh"], "中文译文")

    def test_document_write_projection_translation_zh_defaults_to_none(self) -> None:
        document = MagicMock(metadata={"id": "doc-y"})
        paper = {"source": "x", "channel": "x_daily_watchlist", "title": "Tweet"}

        write = project_document_write(paper, document, "x")

        self.assertIsNone(write["translation_zh"])

    def test_document_write_projection_passes_author_name_through(self) -> None:
        document = MagicMock(metadata={"id": "doc-x-name"})
        paper = {
            "source": "x",
            "channel": "x_daily_watchlist",
            "title": "Tweet",
            "author": "openai",
            "author_name": "OpenAI",
        }

        write = project_document_write(paper, document, "x")

        self.assertEqual(write["author_name"], "OpenAI")

    def test_document_write_projection_author_name_defaults_to_none(self) -> None:
        document = MagicMock(metadata={"id": "doc-x-noname"})
        paper = {"source": "x", "channel": "x_daily_watchlist", "title": "Tweet"}

        write = project_document_write(paper, document, "x")

        self.assertIsNone(write["author_name"])

    def test_document_write_projection_truncates_long_title(self) -> None:
        document = MagicMock(metadata={"id": "doc-x-long"})
        paper = {
            "source": "x",
            "channel": "x_daily_watchlist",
            "title": "长" * 1500,
        }

        write = project_document_write(paper, document, "x")

        # documents.title 为 VARCHAR(1024)：超长标题截断防写入越界
        self.assertEqual(len(write["title"]), 1024)

    def test_document_write_projection_short_title_untouched(self) -> None:
        document = MagicMock(metadata={"id": "doc-x-short"})
        paper = {"source": "x", "channel": "x_daily_watchlist", "title": "Tweet"}

        write = project_document_write(paper, document, "x")

        self.assertEqual(write["title"], "Tweet")

    def test_persist_deletes_channels_before_deterministic_upserts(self) -> None:
        adapter, documents, snapshots, vectors, _, _ = self._adapter()
        events: list[tuple[str, str]] = []
        snapshots.delete_snapshots_by_channel.side_effect = (
            lambda _, channel: events.append(("delete", channel)) or 0
        )
        documents.upsert_document.side_effect = lambda write: events.append(
            ("document", write["title"])
        )
        snapshots.upsert_rank_snapshot.side_effect = lambda **kwargs: events.append(
            ("snapshot", kwargs["doc_id"])
        )
        papers = [
            {"source": "news", "channel": "b", "title": "B", "url": "https://b"},
            {"source": "arxiv", "channel": "a", "title": "A", "url": "https://a"},
        ]

        count = adapter.persist(
            papers, source_label="mixed", snapshot_date="2026-07-24"
        )

        self.assertEqual(count, 2)
        first_document = next(i for i, event in enumerate(events) if event[0] == "document")
        self.assertTrue(all(event[0] == "delete" for event in events[:first_document]))
        self.assertEqual(
            [event[1] for event in events if event[0] == "document"], ["A", "B"]
        )
        vectors.add_documents.assert_called_once()

    def test_persist_skips_delete_for_accumulate_snapshot_channels(self) -> None:
        adapter, documents, snapshots, _, _, _ = self._adapter()
        papers = [
            {
                "source": "x",
                "channel": "x_daily_watchlist",
                "title": "Tweet",
                "url": "https://x.com/a/status/1",
            }
        ]

        count = adapter.persist(papers, source_label="x", snapshot_date="2026-08-06")

        self.assertEqual(count, 1)
        snapshots.delete_snapshots_by_channel.assert_not_called()
        snapshots.upsert_rank_snapshot.assert_called_once()

    def test_persist_mixed_batch_deletes_only_replace_channels(self) -> None:
        adapter, documents, snapshots, _, _, _ = self._adapter()
        papers = [
            {
                "source": "x",
                "channel": "x_daily_watchlist",
                "title": "Tweet",
                "url": "https://x.com/a/status/1",
            },
            {"source": "news", "channel": "news_daily", "title": "N", "url": "https://n"},
        ]

        adapter.persist(papers, source_label="mixed", snapshot_date="2026-08-06")

        snapshots.delete_snapshots_by_channel.assert_called_once_with(
            "2026-08-06", "news_daily"
        )
        self.assertEqual(snapshots.upsert_rank_snapshot.call_count, 2)

    def test_full_multi_store_event_ordering(self) -> None:
        events: list[str] = []
        documents = MagicMock()
        snapshots = MagicMock()
        vectors = MagicMock()
        extractor = MagicMock()
        graph = MagicMock()
        graph_documents = [MagicMock()]
        snapshots.delete_snapshots_by_channel.side_effect = lambda *_: events.append(
            "snapshot-delete"
        )
        documents.upsert_document.side_effect = lambda *_: events.append("document")
        snapshots.upsert_rank_snapshot.side_effect = lambda **_: events.append(
            "snapshot-upsert"
        )
        vectors.add_documents.side_effect = lambda *_args, **_kwargs: events.append(
            "vector"
        )
        extractor.extract.side_effect = lambda *_: events.append("graph-extract") or graph_documents
        graph.add_graph_documents.side_effect = lambda *_: events.append("graph-write")
        graph.close.side_effect = lambda: events.append("graph-close")
        adapter = IngestionPersistenceAdapter(
            documents=documents,
            rank_snapshots=snapshots,
            vector_writer_factory=lambda: events.append("vector-factory") or vectors,
            graph_extractor_factory=lambda: events.append("graph-extractor-factory") or extractor,
            graph_writer_factory=lambda: events.append("graph-writer-factory") or graph,
        )

        count = adapter.persist(
            [
                {
                    "source": "arxiv",
                    "source_channel": "arxiv_daily",
                    "title": "Paper",
                    "url": "https://arxiv.org/abs/2607.1",
                }
            ],
            source_label="arxiv_daily",
            snapshot_date="2026-07-24",
        )

        self.assertEqual(count, 1)
        self.assertEqual(
            events,
            [
                "snapshot-delete",
                "document",
                "snapshot-upsert",
                "vector-factory",
                "vector",
                "graph-extractor-factory",
                "graph-extract",
                "graph-writer-factory",
                "graph-write",
                "graph-close",
            ],
        )

    def test_secondary_store_failures_are_fail_open(self) -> None:
        adapter, documents, snapshots, vectors, extractor, graph = self._adapter()
        snapshots.delete_snapshots_by_channel.side_effect = RuntimeError("delete")
        snapshots.upsert_rank_snapshot.side_effect = RuntimeError("snapshot")
        vectors.add_documents.side_effect = RuntimeError("vector")
        extractor.extract.side_effect = RuntimeError("graph")

        count = adapter.persist(
            [{"source": "arxiv", "channel": "daily", "title": "Paper"}],
            source_label="arxiv_daily",
            snapshot_date="2026-07-24",
        )

        self.assertEqual(count, 1)
        documents.upsert_document.assert_called_once()
        graph.add_graph_documents.assert_not_called()

    def test_document_failure_blocks_vector_and_graph_stores(self) -> None:
        adapter, documents, _, vectors, extractor, graph = self._adapter()
        error = RuntimeError("document")
        documents.upsert_document.side_effect = error

        with self.assertRaises(RuntimeError) as context:
            adapter.persist(
                [{"source": "arxiv", "channel": "daily", "title": "Paper"}],
                source_label="arxiv_daily",
                snapshot_date="2026-07-24",
            )

        self.assertIs(context.exception, error)
        vectors.add_documents.assert_not_called()
        extractor.extract.assert_not_called()
        graph.add_graph_documents.assert_not_called()
        graph.close.assert_not_called()

    def test_vector_factory_failure_is_fail_open_and_graph_still_runs(self) -> None:
        documents = MagicMock()
        snapshots = MagicMock()
        extractor = MagicMock()
        graph = MagicMock()
        vector_factory = MagicMock(side_effect=RuntimeError("vector factory"))
        adapter = IngestionPersistenceAdapter(
            documents=documents,
            rank_snapshots=snapshots,
            vector_writer_factory=vector_factory,
            graph_extractor_factory=MagicMock(return_value=extractor),
            graph_writer_factory=MagicMock(return_value=graph),
        )

        count = adapter.persist(
            [{"source": "arxiv", "channel": "daily", "title": "Paper"}],
            source_label="arxiv_daily",
            snapshot_date="2026-07-24",
        )

        self.assertEqual(count, 1)
        vector_factory.assert_called_once_with()
        extractor.extract.assert_called_once()
        graph.add_graph_documents.assert_called_once()
        graph.close.assert_called_once_with()

    def test_graph_writer_closes_after_successful_local_write(self) -> None:
        adapter, _, _, _, extractor, graph = self._adapter()
        graph_documents = [MagicMock()]
        extractor.extract.return_value = graph_documents

        count = adapter.persist(
            [{"source": "arxiv", "channel": "daily", "title": "Paper"}],
            source_label="arxiv_daily",
            snapshot_date="2026-07-24",
        )

        self.assertEqual(count, 1)
        graph.add_graph_documents.assert_called_once_with(graph_documents)
        graph.close.assert_called_once_with()

    def test_owned_graph_writer_closes_when_write_raises(self) -> None:
        adapter, documents, _, _, extractor, graph = self._adapter()
        extractor.extract.return_value = [MagicMock()]
        graph.add_graph_documents.side_effect = RuntimeError("neo4j unavailable")

        count = adapter.persist(
            [{"source": "arxiv", "channel": "daily", "title": "Paper"}],
            source_label="arxiv_daily",
            snapshot_date="2026-07-24",
        )

        self.assertEqual(count, 1)
        documents.upsert_document.assert_called_once()
        graph.close.assert_called_once_with()

    def test_graph_conditions_skip_non_arxiv_and_reused_documents(self) -> None:
        adapter, _, _, _, extractor, _ = self._adapter()
        adapter.persist(
            [{"source": "news", "title": "News"}],
            source_label="news_daily",
            snapshot_date="2026-07-24",
        )
        extractor.extract.assert_not_called()

        adapter.persist(
            [
                {
                    "source": "arxiv",
                    "title": "Existing",
                    "existing_summary_reused": True,
                }
            ],
            source_label="arxiv_daily",
            snapshot_date="2026-07-24",
        )
        extractor.extract.assert_not_called()

    def test_empty_batch_has_no_side_effects(self) -> None:
        adapter, documents, snapshots, vectors, extractor, graph = self._adapter()

        self.assertEqual(
            adapter.persist([], source_label="news", snapshot_date="2026-07-24"),
            0,
        )
        documents.upsert_document.assert_not_called()
        snapshots.delete_snapshots_by_channel.assert_not_called()
        vectors.add_documents.assert_not_called()
        extractor.extract.assert_not_called()
        graph.add_graph_documents.assert_not_called()


class IngestionTaskLifecycleTests(unittest.TestCase):
    def test_start_success_and_failure_preserve_writer_calls(self) -> None:
        writer = MagicMock()
        writer.create_task.return_value = 42
        lifecycle = IngestionTaskLifecycle(writer)

        self.assertEqual(lifecycle.start("multi_source_ingest"), 42)
        lifecycle.succeed(42, 7)
        error = RuntimeError("sentinel")
        lifecycle.fail(43, error)

        writer.create_task.assert_called_once_with("multi_source_ingest")
        self.assertEqual(
            writer.finish_task.call_args_list[0].kwargs,
            {"status": "success", "error_msg": None, "item_count": 7},
        )
        self.assertEqual(
            writer.finish_task.call_args_list[1].kwargs,
            {"status": "failed", "error_msg": "sentinel", "item_count": 0},
        )


if __name__ == "__main__":
    unittest.main()
