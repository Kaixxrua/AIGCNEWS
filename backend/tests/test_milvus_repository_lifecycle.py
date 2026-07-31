from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.app.repositories.milvus_repo import MilvusRepository


def test_close_releases_owned_embedding_http_client_once() -> None:
    http_client = MagicMock()
    embeddings = MagicMock(http_client=http_client)

    with patch(
        "backend.app.repositories.milvus_repo.get_embedding_model",
        return_value=embeddings,
    ):
        repository = MilvusRepository()

    repository.close()
    repository.close()

    http_client.close.assert_called_once_with()


def test_close_does_not_close_borrowed_embedding_client() -> None:
    http_client = MagicMock()
    embeddings = MagicMock(http_client=http_client)

    repository = MilvusRepository(embeddings=embeddings)
    repository.close()

    http_client.close.assert_not_called()


def test_close_is_noop_when_embedding_has_no_http_client() -> None:
    embeddings = object()

    with patch(
        "backend.app.repositories.milvus_repo.get_embedding_model",
        return_value=embeddings,
    ):
        repository = MilvusRepository()

    repository.close()
    repository.close()
