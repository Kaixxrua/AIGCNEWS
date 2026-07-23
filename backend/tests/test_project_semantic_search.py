from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock, patch

from backend.app.services import project_semantic_search as semantic


class ProjectSemanticSearchTests(unittest.TestCase):
    def tearDown(self) -> None:
        shared = semantic._shared_project_semantic_search
        semantic._shared_project_semantic_search = None
        if shared is not None:
            try:
                shared.close()
            except Exception:
                pass

    def test_shared_accessor_constructs_one_instance_concurrently(self) -> None:
        instances = []

        def get_instance() -> None:
            instances.append(semantic.get_project_semantic_search())

        threads = [threading.Thread(target=get_instance) for _ in range(8)]
        with patch.object(semantic, "ProjectSemanticSearch", wraps=semantic.ProjectSemanticSearch) as factory:
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        self.assertEqual(factory.call_count, 1)
        self.assertTrue(all(instance is instances[0] for instance in instances))

    def test_embedding_model_is_initialized_once_concurrently(self) -> None:
        vectors = MagicMock()
        embeddings = MagicMock()
        embeddings.embed_query.return_value = [0.1, 0.2]
        search = semantic.ProjectSemanticSearch(vectors=vectors)

        with patch(
            "backend.app.core.model_factory.get_embedding_model",
            return_value=embeddings,
        ) as factory:
            threads = [threading.Thread(target=search.warmup) for _ in range(5)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

        factory.assert_called_once_with()

    def test_bilingual_variants_are_fused_by_reciprocal_rank(self) -> None:
        vectors = MagicMock()
        vectors.search_repo_ids.side_effect = [
            [
                semantic.ProjectSemanticHit("owner/a", 0.9),
                semantic.ProjectSemanticHit("owner/b", 0.8),
            ],
            [
                semantic.ProjectSemanticHit("owner/b", 0.95),
                semantic.ProjectSemanticHit("owner/c", 0.7),
            ],
        ]
        embeddings = MagicMock()
        embeddings.embed_query.side_effect = [[0.1, 0.2], [0.3, 0.4]]
        search = semantic.ProjectSemanticSearch(vectors=vectors, embeddings=embeddings)

        with patch.object(semantic.settings, "project_semantic_search_enabled", True):
            hits = search.search_repo_ids("智能体工作流")

        self.assertEqual([hit.repo_id for hit in hits], ["owner/b", "owner/a", "owner/c"])
        self.assertEqual(embeddings.embed_query.call_count, 2)
        self.assertEqual(vectors.search_repo_ids.call_count, 2)

    def test_rrf_deduplicates_each_ranking_and_breaks_ties_by_repo_id(self) -> None:
        rankings = [
            [
                semantic.ProjectSemanticHit("owner/b", 0.9),
                semantic.ProjectSemanticHit("owner/b", 0.8),
            ],
            [semantic.ProjectSemanticHit("owner/a", 0.9)],
        ]

        hits = semantic.reciprocal_rank_fusion(rankings, rank_constant=60, limit=10)

        self.assertEqual([hit.repo_id for hit in hits], ["owner/a", "owner/b"])

    def test_warmup_uses_minimal_vector_search(self) -> None:
        vectors = MagicMock()
        embeddings = MagicMock()
        embeddings.embed_query.return_value = [0.1, 0.2]
        search = semantic.ProjectSemanticSearch(vectors=vectors, embeddings=embeddings)

        search.warmup()

        embeddings.embed_query.assert_called_once()
        vectors.search_repo_ids.assert_called_once_with(
            [0.1, 0.2],
            chunk_limit=1,
            repo_limit=1,
            min_score=-1.0,
        )

    def test_disabled_warmup_does_not_initialize_dependencies(self) -> None:
        with (
            patch.object(semantic.settings, "project_semantic_search_enabled", False),
            patch.object(semantic, "get_project_semantic_search") as get_search,
        ):
            result = semantic.warmup_project_semantic_search()

        self.assertEqual(result, {"status": "disabled"})
        get_search.assert_not_called()

    def test_warmup_failure_is_non_fatal_and_retryable(self) -> None:
        search = MagicMock()
        search.warmup.side_effect = [RuntimeError("temporary"), None]
        with (
            patch.object(semantic.settings, "project_semantic_search_enabled", True),
            patch.object(semantic, "get_project_semantic_search", return_value=search),
        ):
            failed = semantic.warmup_project_semantic_search()
            succeeded = semantic.warmup_project_semantic_search()

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(succeeded["status"], "success")


if __name__ == "__main__":
    unittest.main()
