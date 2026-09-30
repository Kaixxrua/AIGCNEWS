from __future__ import annotations

import hashlib
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from backend.app.repositories.document_vector_repo import DocumentVector
from backend.app.repositories.postgres_document_semantic_source_repository import (
    PostgresDocumentSemanticSourceRepository,
)
from backend.app.services.indexing import document_semantic_indexer as indexer_module
from backend.app.services.indexing.document_semantic_indexer import (
    DocumentSemanticIndexer,
    document_semantic_fingerprint,
    document_semantic_text,
    is_meaningful,
    published_day,
    sync_document_semantic_index,
)

_DIMENSION = 4


def _digest(document: dict) -> str:
    fields = ("source", "published_date", "title", "summary", "tags", "translation_zh")
    return hashlib.md5("\x1f".join(str(document.get(name) or "") for name in fields).encode()).hexdigest()


class FakeSource:
    def __init__(self, documents: list[dict]) -> None:
        self.documents = {document["id"]: document for document in documents}
        self.digest_calls: list[tuple[str, int]] = []

    def list_document_digests(self, *, after_id: str = "", limit: int = 5000) -> list[dict]:
        self.digest_calls.append((after_id, limit))
        rows = sorted(
            (
                {"id": doc_id, "created_at": document.get("created_at", ""), "digest": _digest(document)}
                for doc_id, document in self.documents.items()
                if doc_id > after_id
            ),
            key=lambda row: row["id"],
        )
        return rows[:limit]

    def get_document_semantic_sources(self, doc_ids: list[str]) -> list[dict]:
        return [self.documents[doc_id] for doc_id in doc_ids if doc_id in self.documents]


class FakeVectors:
    def __init__(self, stored: dict[str, DocumentVector] | None = None) -> None:
        self.stored = dict(stored or {})
        self.flushes = 0
        self.closed = False

    def fetch_fingerprints(self, doc_ids) -> dict[str, str]:
        return {doc_id: self.stored[doc_id].fingerprint for doc_id in doc_ids if doc_id in self.stored}

    def list_doc_ids(self) -> set[str]:
        return set(self.stored)

    def upsert_documents(self, vectors) -> int:
        rows = list(vectors)
        for row in rows:
            self.stored[row.doc_id] = row
        return len(rows)

    def delete_documents(self, doc_ids) -> int:
        ids = list(dict.fromkeys(doc_ids))
        for doc_id in ids:
            self.stored.pop(doc_id, None)
        return len(ids)

    def flush(self) -> None:
        self.flushes += 1

    def close(self) -> None:
        self.closed = True


class FakeEmbeddings:
    def __init__(self, fail_on: str | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_on = fail_on

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.fail_on and any(self.fail_on in text for text in texts):
            raise RuntimeError("embedding API HTTP 429")
        return [[float(len(text)), 0.0, 0.0, 1.0] for text in texts]


def _doc(doc_id: str, **fields) -> dict:
    return {
        "id": doc_id,
        "source": "news",
        "published_date": "2026-09-29",
        "title": f"title {doc_id}",
        "summary": f"summary for {doc_id}",
        "tags": "[]",
        "translation_zh": None,
        "created_at": "2026-09-29T10:00:00",
        **fields,
    }


class TextTests(unittest.TestCase):
    def test_x_title_prefix_is_not_repeated_and_translation_is_appended(self) -> None:
        text = document_semantic_text(
            {
                "title": "Excited to release TaskSmith > a specialised harness…",
                "summary": "Excited to release TaskSmith > a specialised harness for RL environments",
                "translation_zh": "很高兴发布 TaskSmith",
                "tags": '["x", "daily", "adithya_s_k"]',
            }
        )
        self.assertEqual(
            text,
            "Excited to release TaskSmith > a specialised harness for RL environments\n"
            "很高兴发布 TaskSmith\nTags: adithya_s_k",
        )

    def test_distinct_title_and_summary_are_both_kept(self) -> None:
        text = document_semantic_text({"title": "GMI Cloud raised $668M", "summary": "The Information: details", "tags": '["Techmeme", "daily"]'})
        self.assertEqual(text, "GMI Cloud raised $668M\nThe Information: details")

    def test_text_is_capped(self) -> None:
        self.assertEqual(len(document_semantic_text({"title": "", "summary": "a" * 5000})), 2000)

    def test_emoji_only_posts_are_not_meaningful(self) -> None:
        self.assertFalse(is_meaningful({"title": "⚡️⚡️", "summary": "⚡️⚡️", "tags": '["Kling_ai"]'}))
        self.assertTrue(is_meaningful({"title": "", "summary": "可灵发布"}))

    def test_published_day(self) -> None:
        self.assertEqual(published_day("2026-09-30T05:49:02"), 20260930)
        self.assertEqual(published_day("2026-09-30"), 20260930)
        self.assertEqual(published_day(""), 0)
        self.assertEqual(published_day("Sep 30"), 0)

    def test_fingerprint_tracks_model_and_version(self) -> None:
        base = document_semantic_fingerprint("abc")
        self.assertEqual(base, document_semantic_fingerprint("abc"))
        self.assertNotEqual(base, document_semantic_fingerprint("abd"))
        with patch.object(indexer_module.settings, "embedding_model_name", "other-model"):
            self.assertNotEqual(base, document_semantic_fingerprint("abc"))
        with patch.object(indexer_module, "DOCUMENT_TEXT_VERSION", "t999"):
            self.assertNotEqual(base, document_semantic_fingerprint("abc"))


class SyncTests(unittest.TestCase):
    def test_first_sync_embeds_every_document_newest_first(self) -> None:
        source = FakeSource([_doc("a", created_at="2026-09-01"), _doc("b", created_at="2026-09-03"), _doc("c", created_at="2026-09-02")])
        vectors = FakeVectors()
        embeddings = FakeEmbeddings()

        result = DocumentSemanticIndexer(db=source, vectors=vectors, embeddings=embeddings).sync()

        self.assertEqual(result["status"], "success")
        self.assertEqual((result["documents"], result["stale"], result["embedded"], result["remaining"]), (3, 3, 3, 0))
        self.assertEqual(embeddings.calls, [[document_semantic_text(source.documents[doc_id]) for doc_id in ("b", "c", "a")]])
        stored = vectors.stored["b"]
        self.assertEqual((stored.source, stored.published_day), ("news", 20260929))
        self.assertEqual(vectors.flushes, 1)

    def test_second_sync_is_a_no_op_until_content_changes(self) -> None:
        source = FakeSource([_doc("a"), _doc("b")])
        vectors = FakeVectors()
        indexer = DocumentSemanticIndexer(db=source, vectors=vectors, embeddings=FakeEmbeddings())
        indexer.sync()

        embeddings = FakeEmbeddings()
        indexer.embeddings = embeddings
        self.assertEqual(indexer.sync()["stale"], 0)
        self.assertEqual(embeddings.calls, [])

        source.documents["b"]["translation_zh"] = "中文译文"
        result = indexer.sync()
        self.assertEqual((result["stale"], result["embedded"]), (1, 1))
        self.assertIn("中文译文", embeddings.calls[0][0])

    def test_max_embed_limits_work_and_reports_remaining(self) -> None:
        source = FakeSource([_doc(str(index)) for index in range(5)])
        result = DocumentSemanticIndexer(db=source, vectors=FakeVectors(), embeddings=FakeEmbeddings()).sync(max_embed=2)
        self.assertEqual((result["embedded"], result["remaining"]), (2, 3))

    def test_deleted_and_meaningless_documents_are_pruned(self) -> None:
        source = FakeSource([_doc("keep"), _doc("emoji", title="⚡️⚡️", summary="⚡️⚡️")])
        stale = DocumentVector("emoji", "x", 0, "old", [0.0] * _DIMENSION)
        orphan = DocumentVector("gone", "x", 0, "old", [0.0] * _DIMENSION)
        vectors = FakeVectors({"emoji": stale, "gone": orphan})

        result = DocumentSemanticIndexer(db=source, vectors=vectors, embeddings=FakeEmbeddings()).sync()

        self.assertEqual(set(vectors.stored), {"keep"})
        self.assertEqual((result["embedded"], result["skipped"], result["pruned"]), (1, 1, 2))

    def test_ids_that_break_milvus_pk_paging_are_not_indexed(self) -> None:
        # pymilvus query_iterator 翻页不转义字符串主键：带引号的 id 进索引后
        # 孤儿扫描会整体报错，所以这类 id 既不嵌入也不算孤儿。
        vectors = FakeVectors()
        source = FakeSource([_doc('q"uote'), _doc("back\\slash"), _doc("plain")])
        result = DocumentSemanticIndexer(db=source, vectors=vectors, embeddings=FakeEmbeddings()).sync()
        self.assertEqual(set(vectors.stored), {"plain"})
        self.assertEqual((result["documents"], result["stale"], result["pruned"]), (3, 1, 0))

    def test_orphan_scan_failure_skips_pruning_only(self) -> None:
        vectors = FakeVectors()
        vectors.list_doc_ids = MagicMock(side_effect=RuntimeError("iterator failed"))
        result = DocumentSemanticIndexer(db=FakeSource([_doc("a")]), vectors=vectors, embeddings=FakeEmbeddings()).sync()
        self.assertEqual((result["status"], result["embedded"], result["pruned"]), ("success", 1, 0))

    def test_prune_can_be_disabled(self) -> None:
        orphan = DocumentVector("gone", "x", 0, "old", [0.0] * _DIMENSION)
        vectors = FakeVectors({"gone": orphan})
        DocumentSemanticIndexer(db=FakeSource([]), vectors=vectors, embeddings=FakeEmbeddings()).sync(prune=False)
        self.assertIn("gone", vectors.stored)

    def test_failed_batches_are_counted_and_do_not_stop_the_sweep(self) -> None:
        source = FakeSource([_doc("a", summary="poison"), _doc("b")])
        with patch.object(indexer_module.settings, "document_semantic_embed_batch_size", 1):
            result = DocumentSemanticIndexer(db=source, vectors=(vectors := FakeVectors()), embeddings=FakeEmbeddings(fail_on="poison")).sync()
        self.assertEqual((result["status"], result["embedded"], result["failed"]), ("success", 1, 1))
        self.assertEqual(set(vectors.stored), {"b"})

    def test_all_batches_failing_reports_failure(self) -> None:
        source = FakeSource([_doc("a", summary="poison")])
        result = DocumentSemanticIndexer(db=source, vectors=FakeVectors(), embeddings=FakeEmbeddings(fail_on="poison")).sync()
        self.assertEqual(result["status"], "failed")

    def test_dry_run_writes_nothing(self) -> None:
        source = FakeSource([_doc("a")])
        vectors = FakeVectors()
        embeddings = FakeEmbeddings()
        result = DocumentSemanticIndexer(db=source, vectors=vectors, embeddings=embeddings).sync(dry_run=True)
        self.assertEqual((result["status"], result["stale"]), ("dry_run", 1))
        self.assertEqual((vectors.stored, embeddings.calls), ({}, []))

    def test_digest_scan_pages_by_keyset(self) -> None:
        source = FakeSource([_doc(f"{index:03d}") for index in range(7)])
        with patch.object(indexer_module, "_DIGEST_PAGE", 3):
            result = DocumentSemanticIndexer(db=source, vectors=FakeVectors(), embeddings=FakeEmbeddings()).sync()
        self.assertEqual(result["documents"], 7)
        self.assertEqual([after for after, _ in source.digest_calls], ["", "002", "005"])

    def test_disabled_flag_short_circuits_unless_forced(self) -> None:
        with patch.object(indexer_module.settings, "document_semantic_indexing_enabled", False):
            self.assertEqual(sync_document_semantic_index(db=FakeSource([]))["status"], "disabled")

    def test_forced_run_closes_the_vector_connection(self) -> None:
        vectors = FakeVectors()
        with patch.object(indexer_module, "DocumentVectorRepository", return_value=vectors):
            result = sync_document_semantic_index(db=FakeSource([]), force=True)
        self.assertEqual(result["status"], "success")
        self.assertTrue(vectors.closed)


class PostgresSourceTests(unittest.TestCase):
    def _repository(self, rows: list[dict]):
        cursor = MagicMock()
        cursor.fetchall.return_value = rows
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor

        class Database:
            @contextmanager
            def transaction(self):
                yield connection

        return PostgresDocumentSemanticSourceRepository(Database()), cursor

    def test_digest_query_covers_embedded_columns_and_keysets_by_c_collation(self) -> None:
        repository, cursor = self._repository([{"id": "a", "created_at": "x", "digest": "d"}])
        self.assertEqual(repository.list_document_digests(after_id="a", limit=10), [{"id": "a", "created_at": "x", "digest": "d"}])
        sql, params = cursor.execute.call_args.args
        for column in ("source", "published_date", "title", "summary", "tags", "translation_zh"):
            self.assertIn(f"COALESCE({column}, '')", sql)
        self.assertIn('ORDER BY id COLLATE "C" ASC', sql)
        self.assertEqual(params, ("a", 10))

    def test_sources_are_fetched_by_id_array(self) -> None:
        repository, cursor = self._repository([])
        self.assertEqual(repository.get_document_semantic_sources([]), [])
        cursor.execute.assert_not_called()
        repository.get_document_semantic_sources(["a", "b"])
        sql, params = cursor.execute.call_args.args
        self.assertIn("WHERE id = ANY(%s)", sql)
        self.assertEqual(params, (["a", "b"],))


if __name__ == "__main__":
    unittest.main()
