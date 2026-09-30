from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.repositories.project_vector_repo import (
    ProjectVectorChunk,
    ProjectVectorRepository,
    ProjectVectorSchemaError,
    ProjectVectorUnavailableError,
)


class ProjectVectorRepositoryTests(unittest.TestCase):
    def test_dimension_mismatch_fails_before_writing(self) -> None:
        repository = ProjectVectorRepository(collection_name="test", dimension=3)
        repository.ensure_collection = MagicMock()
        chunk = ProjectVectorChunk("id", "repo", "profile", 0, "f", "content", [1.0, 2.0])

        with self.assertRaises(ProjectVectorSchemaError):
            repository.upsert_project_chunks("repo", [chunk])

        repository.ensure_collection.return_value.upsert.assert_not_called()

    def test_upsert_removes_only_obsolete_chunks(self) -> None:
        repository = ProjectVectorRepository(collection_name="test", dimension=2)
        collection = MagicMock()
        collection.query.return_value = [{"chunk_id": "keep"}, {"chunk_id": "old"}]
        repository.ensure_collection = MagicMock(return_value=collection)
        chunk = ProjectVectorChunk("keep", "repo", "profile", 0, "f", "content", [1.0, 2.0])

        count = repository.upsert_project_chunks("repo", [chunk])

        self.assertEqual(count, 1)
        collection.upsert.assert_called_once()
        collection.delete.assert_called_once_with('chunk_id in ["old"]')
        collection.flush.assert_called_once()

    def test_schema_mismatch_never_drops_collection(self) -> None:
        repository = ProjectVectorRepository(collection_name="test", dimension=2)
        collection = MagicMock()
        collection.schema.fields = []

        with self.assertRaises(ProjectVectorSchemaError):
            repository._validate_collection(collection)

        self.assertFalse(hasattr(collection, "drop") and collection.drop.called)

    def test_search_loads_collection_only_once(self) -> None:
        repository = ProjectVectorRepository(collection_name="test", dimension=2)
        collection = MagicMock()
        collection.search.return_value = [[]]
        repository.ensure_collection = MagicMock(return_value=collection)

        repository.search_repo_ids([0.1, 0.2], chunk_limit=5, repo_limit=2, min_score=0)
        repository.search_repo_ids([0.1, 0.2], chunk_limit=5, repo_limit=2, min_score=0)

        collection.load.assert_called_once_with()

    def test_failed_load_is_retried(self) -> None:
        repository = ProjectVectorRepository(collection_name="test", dimension=2)
        collection = MagicMock()
        collection.load.side_effect = [RuntimeError("temporary"), None]
        repository.ensure_collection = MagicMock(return_value=collection)

        with self.assertRaises(ProjectVectorUnavailableError):
            repository.search_repo_ids([0.1, 0.2], chunk_limit=5, repo_limit=2, min_score=0)
        collection.search.return_value = [[]]
        repository.search_repo_ids([0.1, 0.2], chunk_limit=5, repo_limit=2, min_score=0)

        self.assertEqual(collection.load.call_count, 2)

    def test_count_project_chunks_quotes_repo_id(self) -> None:
        repository = ProjectVectorRepository(collection_name="test", dimension=2)
        collection = MagicMock()
        collection.query.return_value = [{"chunk_id": "one"}, {"chunk_id": "two"}]
        repository.ensure_collection = MagicMock(return_value=collection)

        count = repository.count_project_chunks('owner/"repo')

        self.assertEqual(count, 2)
        self.assertEqual(collection.query.call_args.kwargs["expr"], 'repo_id == "owner/\\"repo"')

    def test_delete_project_is_scoped_to_repo_id(self) -> None:
        repository = ProjectVectorRepository(collection_name="test", dimension=2)
        collection = MagicMock()
        repository.ensure_collection = MagicMock(return_value=collection)

        repository.delete_project('owner/"repo')

        collection.delete.assert_called_once_with('repo_id == "owner/\\"repo"')
        collection.flush.assert_called_once_with()

    def test_close_disconnects_once(self) -> None:
        repository = ProjectVectorRepository(collection_name="test", dimension=2)
        repository._connected = True
        with patch("pymilvus.connections.disconnect") as disconnect:
            repository.close()
            repository.close()

        disconnect.assert_called_once_with("project_semantic")


    def test_list_repo_ids_drains_iterator_and_drops_blanks(self) -> None:
        repository = ProjectVectorRepository(collection_name="test", dimension=2)
        collection = MagicMock()
        iterator = MagicMock()
        iterator.next.side_effect = [
            [{"repo_id": "a/one"}, {"repo_id": "a/one"}, {"repo_id": ""}],
            [{"repo_id": "b/two"}],
            [],
        ]
        collection.query_iterator.return_value = iterator
        repository._load_collection = MagicMock(return_value=collection)

        self.assertEqual(repository.list_repo_ids(batch_size=2), {"a/one", "b/two"})
        collection.query_iterator.assert_called_once_with(
            batch_size=2, expr='repo_id != ""', output_fields=["repo_id"]
        )
        iterator.close.assert_called_once_with()

    def test_list_repo_ids_closes_iterator_on_error(self) -> None:
        repository = ProjectVectorRepository(collection_name="test", dimension=2)
        collection = MagicMock()
        iterator = MagicMock()
        iterator.next.side_effect = RuntimeError("boom")
        collection.query_iterator.return_value = iterator
        repository._load_collection = MagicMock(return_value=collection)

        with self.assertRaises(RuntimeError):
            repository.list_repo_ids()
        iterator.close.assert_called_once_with()

if __name__ == "__main__":
    unittest.main()
