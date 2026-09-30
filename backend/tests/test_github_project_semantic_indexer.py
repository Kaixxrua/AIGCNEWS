from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from backend.app.services.indexing.github_project_semantic_indexer import (
    GitHubProjectSemanticIndexer,
    build_project_semantic_chunks,
    project_semantic_fingerprint,
    sync_github_project_semantic_index,
)

PROJECT = {
    "repo_id": "owner/repo",
    "full_name": "owner/repo",
    "title": "owner/repo",
    "description": "Frontend development toolkit",
    "description_zh": "前端开发工具",
    "category_slug": "coding_tools",
    "category_name": "编程工具",
    "subcategory_slug": "frameworks",
    "subcategory_name": "框架",
    "tags_json": '["前端"]',
    "topics_json": '["frontend"]',
    "language": "TypeScript",
    "pushed_at": "2026-07-22",
}


class GitHubProjectSemanticIndexerTests(unittest.TestCase):
    def test_profile_exists_without_readme(self) -> None:
        chunks = build_project_semantic_chunks(PROJECT, "")
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0][0], "profile")
        self.assertIn("Frontend development toolkit", chunks[0][2])
        self.assertIn("前端开发工具", chunks[0][2])

    def test_metrics_do_not_change_fingerprint(self) -> None:
        first = project_semantic_fingerprint(PROJECT, "abc")
        changed = {**PROJECT, "stars": 100_000, "forks": 3_000}
        self.assertEqual(first, project_semantic_fingerprint(changed, "abc"))

    def test_normalized_topics_and_tags_are_embedded_and_fingerprinted(self) -> None:
        normalized = {
            **PROJECT,
            "topics": ["frontend", "developer-tools"],
            "tags": ["前端", "开发工具"],
        }
        normalized.pop("topics_json")
        normalized.pop("tags_json")

        chunks = build_project_semantic_chunks(normalized, "")
        changed = {**normalized, "topics": ["frontend", "design-system"]}

        self.assertIn("Tags: 前端, 开发工具", chunks[0][2])
        self.assertIn("Topics: frontend, developer-tools", chunks[0][2])
        self.assertNotEqual(
            project_semantic_fingerprint(normalized, "abc"),
            project_semantic_fingerprint(changed, "abc"),
        )

    def test_sync_project_uses_one_repo_id_for_vector_and_status(self) -> None:
        canonical = {**PROJECT, "repo_id": "owner/canonical"}
        db = MagicMock()
        vectors = MagicMock()
        vectors.upsert_project_chunks.return_value = 1
        embeddings = MagicMock()
        embeddings.embed_documents.return_value = [[0.1] * 1024]
        indexer = GitHubProjectSemanticIndexer(db=db, vectors=vectors, embeddings=embeddings)

        result = indexer.sync_project(canonical, fetch_readme=False)

        self.assertEqual(result["repo_id"], "owner/canonical")
        self.assertEqual(vectors.upsert_project_chunks.call_args.args[0], "owner/canonical")
        self.assertEqual(vectors.upsert_project_chunks.call_args.args[1][0].repo_id, "owner/canonical")
        self.assertTrue(
            all(
                call.args[0]["repo_id"] == "owner/canonical"
                for call in db.upsert_github_project_semantic_source.call_args_list
            )
        )

    def test_sync_project_upserts_stable_chunks_and_status(self) -> None:
        db = MagicMock()
        vectors = MagicMock()
        vectors.upsert_project_chunks.return_value = 1
        embeddings = MagicMock()
        embeddings.embed_documents.return_value = [[0.1] * 1024]
        indexer = GitHubProjectSemanticIndexer(db=db, vectors=vectors, embeddings=embeddings)

        result = indexer.sync_project(PROJECT, fetch_readme=False)

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(db.upsert_github_project_semantic_source.call_count, 2)
        vector_chunk = vectors.upsert_project_chunks.call_args.args[1][0]
        self.assertEqual(vector_chunk.repo_id, "owner/repo")
        self.assertEqual(len(vector_chunk.chunk_id), 64)
        self.assertEqual(vector_chunk.chunk_kind, "profile")

    def test_index_failure_is_recorded_without_raising(self) -> None:
        db = MagicMock()
        vectors = MagicMock()
        vectors.upsert_project_chunks.side_effect = RuntimeError("milvus unavailable")
        embeddings = MagicMock()
        embeddings.embed_documents.return_value = [[0.1] * 1024]
        indexer = GitHubProjectSemanticIndexer(db=db, vectors=vectors, embeddings=embeddings)

        result = indexer.sync_project(PROJECT, fetch_readme=False)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(db.upsert_github_project_semantic_source.call_args.args[0]["index_status"], "failed")

    def test_sync_batch_runs_requested_concurrency_and_keeps_cursor_order(self) -> None:
        projects = [{**PROJECT, "repo_id": f"owner/repo-{index}"} for index in range(12)]
        db = MagicMock()
        db.list_github_projects_for_semantic_sync.return_value = projects
        db.list_indexed_github_project_ids.return_value = []
        embeddings = MagicMock()
        indexer = GitHubProjectSemanticIndexer(db=db, embeddings=embeddings)
        active = 0
        max_active = 0
        lock = threading.Lock()

        def sync_project(project, **_kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.01)
            with lock:
                active -= 1
            return {"repo_id": project["repo_id"], "status": "succeeded", "chunk_count": 1}

        indexer.sync_project = MagicMock(side_effect=sync_project)
        result = indexer.sync_batch(limit=12, concurrency=20, fetch_readme=False)

        self.assertGreater(max_active, 1)
        self.assertLessEqual(max_active, 20)
        self.assertEqual(result["counts"], {"succeeded": 12})
        self.assertEqual(result["last_repo_id"], "owner/repo-11")

    def test_sync_batch_isolates_unexpected_worker_failure(self) -> None:
        projects = [{**PROJECT, "repo_id": "owner/ok"}, {**PROJECT, "repo_id": "owner/bad"}]
        db = MagicMock()
        db.list_github_projects_for_semantic_sync.return_value = projects
        db.list_indexed_github_project_ids.return_value = []
        embeddings = MagicMock()
        indexer = GitHubProjectSemanticIndexer(db=db, embeddings=embeddings)

        def sync_project(project, **_kwargs):
            if project["repo_id"] == "owner/bad":
                raise RuntimeError("unexpected")
            return {"repo_id": project["repo_id"], "status": "succeeded", "chunk_count": 1}

        indexer.sync_project = MagicMock(side_effect=sync_project)
        result = indexer.sync_batch(limit=2, concurrency=2, fetch_readme=False)

        self.assertEqual(result["counts"], {"succeeded": 1, "failed": 1})

    def test_unchanged_project_advances_snapshot_watermark_without_vector_writes(self) -> None:
        fingerprint = project_semantic_fingerprint(PROJECT, "")
        project = {
            **PROJECT,
            "indexed_fingerprint": fingerprint,
            "pushed_at": "2026-08-01",
        }
        db = MagicMock()
        vectors = MagicMock()
        indexer = GitHubProjectSemanticIndexer(
            db=db, vectors=vectors, embeddings=MagicMock()
        )

        result = indexer.sync_project(project, fetch_readme=False)

        self.assertEqual(result["status"], "unchanged")
        vectors.upsert_project_chunks.assert_not_called()
        db.mark_github_project_semantic_snapshot_current.assert_called_once()
        mark_kwargs = db.mark_github_project_semantic_snapshot_current.call_args
        self.assertEqual(mark_kwargs.args[0], "owner/repo")
        self.assertEqual(mark_kwargs.kwargs["repo_pushed_at"], "2026-08-01")
        self.assertTrue(mark_kwargs.kwargs["checked_at"])

    def test_sync_batch_defers_flush_to_batch_end(self) -> None:
        projects = [{**PROJECT, "repo_id": f"owner/repo-{index}"} for index in range(2)]
        db = MagicMock()
        db.list_github_projects_for_semantic_sync.return_value = projects
        db.list_indexed_github_project_ids.return_value = []
        vectors = MagicMock()
        vectors.upsert_project_chunks.return_value = 1
        embeddings = MagicMock()
        embeddings.embed_documents.return_value = [[0.1] * 1024]
        indexer = GitHubProjectSemanticIndexer(db=db, vectors=vectors, embeddings=embeddings)

        result = indexer.sync_batch(limit=2, concurrency=2, fetch_readme=False)

        self.assertEqual(result["counts"], {"succeeded": 2})
        for call in vectors.upsert_project_chunks.call_args_list:
            self.assertIs(call.kwargs["flush"], False)
        vectors.flush.assert_called_once_with()

    def test_concurrent_dry_run_does_not_load_embedding_model(self) -> None:
        projects = [{**PROJECT, "repo_id": f"owner/repo-{index}"} for index in range(2)]
        db = MagicMock()
        db.list_github_projects_for_semantic_sync.return_value = projects
        db.list_indexed_github_project_ids.return_value = []
        indexer = GitHubProjectSemanticIndexer(db=db)

        with patch.object(indexer, "_embeddings") as embeddings:
            result = indexer.sync_batch(limit=2, concurrency=2, fetch_readme=False, dry_run=True)

        self.assertEqual(result["counts"], {"dry_run": 2})
        embeddings.assert_not_called()


class GitHubProjectSemanticLedgerReconcileTests(unittest.TestCase):
    def test_requeues_projects_missing_from_milvus(self) -> None:
        db = MagicMock()
        db.list_indexed_github_project_ids.return_value = ["a/one", "b/two", "c/three"]
        db.requeue_github_project_semantic_index.return_value = 2
        vectors = MagicMock()
        vectors.list_repo_ids.return_value = {"a/one", "z/orphan"}
        indexer = GitHubProjectSemanticIndexer(db=db, vectors=vectors, embeddings=MagicMock())

        result = indexer.reconcile_vector_ledger()

        self.assertEqual(result, {"status": "success", "indexed": 3, "missing": 2, "requeued": 2})
        args, kwargs = db.requeue_github_project_semantic_index.call_args
        self.assertEqual(args[0], ["b/two", "c/three"])
        self.assertIn("missing from Milvus", kwargs["reason"])
        self.assertTrue(kwargs["updated_at"])

    def test_dry_run_reports_without_requeue(self) -> None:
        db = MagicMock()
        db.list_indexed_github_project_ids.return_value = ["a/one", "b/two"]
        vectors = MagicMock()
        vectors.list_repo_ids.return_value = {"a/one"}
        indexer = GitHubProjectSemanticIndexer(db=db, vectors=vectors)

        result = indexer.reconcile_vector_ledger(dry_run=True)

        self.assertEqual(result, {"status": "dry_run", "indexed": 2, "missing": 1, "requeued": 0})
        db.requeue_github_project_semantic_index.assert_not_called()

    def test_unreadable_milvus_leaves_ledger_untouched(self) -> None:
        db = MagicMock()
        db.list_indexed_github_project_ids.return_value = ["a/one"]
        vectors = MagicMock()
        vectors.list_repo_ids.side_effect = RuntimeError("milvus down")
        indexer = GitHubProjectSemanticIndexer(db=db, vectors=vectors)

        result = indexer.reconcile_vector_ledger()

        self.assertEqual(result["status"], "failed")
        self.assertIn("milvus down", result["error"])
        db.requeue_github_project_semantic_index.assert_not_called()

    def test_empty_ledger_skips_milvus(self) -> None:
        db = MagicMock()
        db.list_indexed_github_project_ids.return_value = []
        vectors = MagicMock()
        indexer = GitHubProjectSemanticIndexer(db=db, vectors=vectors)

        result = indexer.reconcile_vector_ledger()

        self.assertEqual(result, {"status": "success", "indexed": 0, "missing": 0, "requeued": 0})
        vectors.list_repo_ids.assert_not_called()

    def test_sync_batch_reconciles_before_selecting(self) -> None:
        manager = MagicMock()
        db = manager.db
        db.list_indexed_github_project_ids.return_value = ["a/one"]
        db.requeue_github_project_semantic_index.return_value = 1
        db.list_github_projects_for_semantic_sync.return_value = []
        vectors = manager.vectors
        vectors.list_repo_ids.return_value = set()
        indexer = GitHubProjectSemanticIndexer(db=db, vectors=vectors, embeddings=MagicMock())

        result = indexer.sync_batch(limit=5, fetch_readme=False)

        self.assertEqual(result["reconcile"]["requeued"], 1)
        names = [name for name, _, _ in manager.mock_calls]
        self.assertLess(
            names.index("db.requeue_github_project_semantic_index"),
            names.index("db.list_github_projects_for_semantic_sync"),
        )

    def test_sync_batch_can_skip_reconcile(self) -> None:
        db = MagicMock()
        db.list_github_projects_for_semantic_sync.return_value = []
        indexer = GitHubProjectSemanticIndexer(db=db, vectors=MagicMock())

        result = indexer.sync_batch(limit=5, fetch_readme=False, reconcile=False)

        self.assertNotIn("reconcile", result)
        db.list_indexed_github_project_ids.assert_not_called()


class SyncGitHubProjectSemanticIndexTests(unittest.TestCase):
    def test_force_is_popped_before_reaching_sync_batch_when_enabled(self) -> None:
        db = MagicMock()
        db.list_github_projects_for_semantic_sync.return_value = []
        with (
            patch(
                "backend.app.services.indexing.github_project_semantic_indexer.settings.project_semantic_indexing_enabled",
                True,
            ),
            patch.object(GitHubProjectSemanticIndexer, "sync_batch", return_value={"status": "success"}) as sync_batch,
        ):
            result = sync_github_project_semantic_index(db=db, force=True, limit=5)

        self.assertEqual(result, {"status": "success"})
        self.assertNotIn("force", sync_batch.call_args.kwargs)

    def test_disabled_without_force_short_circuits(self) -> None:
        with patch(
            "backend.app.services.indexing.github_project_semantic_indexer.settings.project_semantic_indexing_enabled",
            False,
        ):
            result = sync_github_project_semantic_index(db=MagicMock())

        self.assertEqual(result, {"status": "disabled", "selected": 0, "counts": {}})


if __name__ == "__main__":
    unittest.main()
