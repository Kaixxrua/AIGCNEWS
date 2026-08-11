from __future__ import annotations

import hashlib
import unittest
from unittest.mock import MagicMock

from backend.app.services.ingestion.document_projection import (
    project_documents as _to_documents,
)
from backend.app.services.ingestion.pipeline import (
    _apply_existing_summary_short_circuit,
    _doc_id,
    _ingest_documents,
    _select_top,
)


class DocumentProjectionContractTests(unittest.TestCase):
    def test_doc_id_preserves_identity_precedence_and_ignores_period(self) -> None:
        arxiv = {
            "source": "arxiv",
            "arxiv_id": "2607.00001",
            "full_name": "ignored/repo",
            "url": "https://ignored.example/paper",
            "title": "Ignored",
            "source_channel": "huggingface_daily_html",
            "in_daily": 1,
        }
        expected_arxiv = hashlib.md5(b"arxiv:2607.00001").hexdigest()
        self.assertEqual(_doc_id(arxiv), expected_arxiv)
        self.assertEqual(
            _doc_id(
                {
                    **arxiv,
                    "source_channel": "huggingface_monthly_html",
                    "in_daily": 0,
                    "in_monthly": 1,
                }
            ),
            expected_arxiv,
        )

        github = {
            "source": "github",
            "full_name": "owner/repo",
            "url": "https://github.com/ignored/repo",
            "title": "Ignored",
        }
        self.assertEqual(
            _doc_id(github),
            hashlib.md5(b"github:owner/repo").hexdigest(),
        )
        generic = {"source": "news", "url": "https://example.test/item", "title": "Ignored"}
        self.assertEqual(
            _doc_id(generic),
            hashlib.md5(b"news:https://example.test/item").hexdigest(),
        )
        self.assertEqual(
            _doc_id({"source": "news", "title": "Fallback"}),
            hashlib.md5(b"news:Fallback").hexdigest(),
        )

    def test_document_projection_preserves_content_precedence_and_defaults(self) -> None:
        papers = [
            {
                "source": "github",
                "title": "Full",
                "full_text": "full text",
                "abstract": "abstract",
                "summary": "summary",
                "stars": "12",
                "score": "3.5",
                "channel": "github_trending_daily",
                "in_daily": 1,
            },
            {"title": "Abstract", "abstract": "abstract only", "stars": "invalid"},
            {"title": "Summary", "summary": "summary only"},
            {"title": "Title only"},
        ]

        documents = _to_documents(papers)

        self.assertEqual(
            [document.page_content for document in documents],
            ["full text", "abstract only", "summary only", "Title only"],
        )
        self.assertEqual(documents[0].metadata["stars"], 12)
        self.assertEqual(documents[0].metadata["raw_score"], 3.5)
        self.assertEqual(documents[0].metadata["source_channel"], "github_trending_daily")
        self.assertEqual(documents[0].metadata["in_daily"], 1)
        self.assertEqual(documents[1].metadata["source"], "unknown")
        self.assertEqual(documents[1].metadata["stars"], 0)
        self.assertEqual(documents[1].metadata["raw_score"], 0.0)
        self.assertEqual(documents[1].metadata["url"], "")
        self.assertEqual(documents[1].metadata["in_monthly"], 0)

    def test_existing_summary_reuse_mutates_original_paper_in_place(self) -> None:
        paper = {
            "source": "news",
            "title": "Existing",
            "url": "https://example.test/existing",
        }
        papers = [paper]
        reader = MagicMock()
        reader.get_existing_document_summaries.return_value = {
            f"id:{_doc_id(paper)}": "stored summary"
        }

        result = _apply_existing_summary_short_circuit(papers, reader, "news_daily")

        self.assertIs(result, papers)
        self.assertIs(result[0], paper)
        self.assertEqual(paper["summary"], "stored summary")
        self.assertEqual(paper["abstract"], "stored summary")
        self.assertEqual(paper["full_text"], "stored summary")
        self.assertTrue(paper["skip_enrich"])
        self.assertTrue(paper["existing_summary_reused"])

    def test_top_n_uses_raw_score_then_returns_stable_write_order(self) -> None:
        papers = [
            {"source": "news", "title": "B", "url": "https://b", "score": 20},
            {"source": "arxiv", "title": "A", "url": "https://a", "raw_score": 30},
            {"source": "github", "title": "C", "url": "https://c", "score": 10},
        ]

        selected = _select_top(papers, top_n=2, source_label="contract")

        self.assertEqual({paper["title"] for paper in selected}, {"A", "B"})
        self.assertEqual([paper["source"] for paper in selected], ["arxiv", "news"])
        self.assertEqual([paper["title"] for paper in papers], ["A", "B", "C"])


class PersistenceProjectionContractTests(unittest.TestCase):
    def test_document_writes_precede_atomic_channel_snapshot_replacement(self) -> None:
        events: list[tuple] = []
        writer = MagicMock()
        snapshots = MagicMock()
        snapshots.replace_channel_snapshots.side_effect = (
            lambda snapshot_date, channel, rows: events.append(
                ("replace", snapshot_date, channel, [row["doc_id"] for row in rows])
            )
            or len(rows)
        )
        writer.upsert_document.side_effect = lambda document: events.append(
            ("document", document["title"])
        )
        snapshots.upsert_rank_snapshot.side_effect = lambda **kwargs: events.append(
            ("snapshot", kwargs["doc_id"], kwargs["snapshot_date"])
        )
        papers = [
            {
                "source": "news",
                "source_channel": "channel_b",
                "title": "B",
                "url": "https://b",
                "raw_score": 2,
                "rank_in_period": 2,
            },
            {
                "source": "arxiv",
                "source_channel": "channel_a",
                "title": "A",
                "url": "https://a",
                "raw_score": 3,
                "rank_in_period": 1,
            },
        ]

        count = _ingest_documents(
            papers,
            42,
            "mixed",
            "2026-07-24",
            document_writer=writer,
            rank_snapshots=snapshots,
            vector_writer_factory=MagicMock(),
            graph_extractor_factory=MagicMock(),
            graph_writer_factory=MagicMock(),
        )

        self.assertEqual(count, 2)
        # 文档按确定性顺序全部写完后，才逐 channel 原子替换快照；
        # 替换型 channel 不再逐行 upsert（删除在仓储事务内完成）。
        first_write = next(index for index, event in enumerate(events) if event[0] == "document")
        self.assertEqual(events[:first_write], [])
        self.assertEqual(
            [event[1] for event in events if event[0] == "document"],
            ["A", "B"],
        )
        self.assertEqual(
            sorted(event[2] for event in events if event[0] == "replace"),
            ["channel_a", "channel_b"],
        )
        self.assertEqual(
            [event[1] for event in events if event[0] == "replace"],
            ["2026-07-24", "2026-07-24"],
        )
        self.assertTrue(all(len(event[3]) == 1 for event in events if event[0] == "replace"))
        self.assertEqual([event for event in events if event[0] == "snapshot"], [])
        snapshots.delete_snapshots_by_channel.assert_not_called()

    def test_secondary_store_failures_are_fail_open_and_arxiv_graph_skips_reused(self) -> None:
        writer = MagicMock()
        snapshots = MagicMock()
        snapshots.delete_snapshots_by_channel.side_effect = RuntimeError("delete failed")
        snapshots.upsert_rank_snapshot.side_effect = RuntimeError("snapshot failed")
        new_paper = {
            "source": "arxiv",
            "source_channel": "huggingface_daily_html",
            "title": "New",
            "url": "https://new",
        }
        reused_paper = {
            "source": "arxiv",
            "source_channel": "huggingface_daily_html",
            "title": "Reused",
            "url": "https://reused",
            "existing_summary_reused": True,
        }

        milvus_type = MagicMock()
        extractor_type = MagicMock()
        graph_type = MagicMock()
        milvus_type.return_value.add_documents.side_effect = RuntimeError("milvus failed")
        extractor_type.return_value.extract.return_value = ["graph-document"]
        count = _ingest_documents(
            [reused_paper, new_paper],
            42,
            "arxiv_daily",
            "2026-07-24",
            document_writer=writer,
            rank_snapshots=snapshots,
            vector_writer_factory=milvus_type,
            graph_extractor_factory=extractor_type,
            graph_writer_factory=graph_type,
        )

        self.assertEqual(count, 2)
        self.assertEqual(writer.upsert_document.call_count, 2)
        extracted_documents = extractor_type.return_value.extract.call_args.args[0]
        self.assertEqual(len(extracted_documents), 1)
        self.assertEqual(extracted_documents[0].metadata["title"], "New")
        graph_type.return_value.add_graph_documents.assert_called_once_with(["graph-document"])
        graph_type.return_value.close.assert_called_once_with()

    def test_non_arxiv_source_never_constructs_graph_dependencies(self) -> None:
        db = MagicMock()
        extractor_type = MagicMock()
        graph_type = MagicMock()
        count = _ingest_documents(
            [{"source": "news", "title": "Item", "url": "https://item"}],
            1,
            "news_daily",
            "2026-07-24",
            document_writer=db.documents,
            rank_snapshots=db.rank_snapshots,
            vector_writer_factory=MagicMock(),
            graph_extractor_factory=extractor_type,
            graph_writer_factory=graph_type,
        )

        self.assertEqual(count, 1)
        extractor_type.assert_not_called()
        graph_type.assert_not_called()


if __name__ == "__main__":
    unittest.main()
