from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from backend.app.repositories.project_vector_repo import (
    ProjectVectorChunk,
    ProjectVectorRepository,
    ProjectVectorSchemaError,
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

if __name__ == "__main__":
    unittest.main()
