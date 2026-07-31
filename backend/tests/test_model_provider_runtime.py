from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.runtime_provider.runtime import (
    ApplicationModelProviderRuntime,
)


def test_runtime_caches_chat_by_temperature_and_embedding_independently() -> None:
    chats: list[object] = []
    embeddings: list[object] = []

    def chat_factory(temperature: float | None) -> object:
        model = (temperature, object())
        chats.append(model)
        return model

    def embedding_factory() -> object:
        model = object()
        embeddings.append(model)
        return model

    runtime = ApplicationModelProviderRuntime(
        chat_factory=chat_factory,
        embedding_factory=embedding_factory,
    )

    assert runtime.get_chat_model() is runtime.get_chat_model()
    assert runtime.get_chat_model(0) is runtime.get_chat_model(0)
    assert runtime.get_chat_model() is not runtime.get_chat_model(0)
    assert runtime.get_embedding_model() is runtime.get_embedding_model()
    assert len(chats) == 2
    assert len(embeddings) == 1


def test_runtime_invalidation_closes_detached_provider_resources() -> None:
    chat_client = MagicMock()
    chat = MagicMock(client=chat_client)
    embedding_client = MagicMock()
    embedding = MagicMock(http_client=embedding_client)
    runtime = ApplicationModelProviderRuntime(
        chat_factory=MagicMock(return_value=chat),
        embedding_factory=MagicMock(return_value=embedding),
    )

    assert runtime.get_chat_model() is chat
    assert runtime.get_embedding_model() is embedding
    asyncio.run(runtime.invalidate())

    chat_client.close.assert_called_once_with()
    embedding_client.close.assert_called_once_with()
    assert runtime.get_chat_model() is chat


def test_runtime_close_is_idempotent_and_rejects_new_models() -> None:
    model = MagicMock()
    runtime = ApplicationModelProviderRuntime(
        chat_factory=MagicMock(return_value=model),
        embedding_factory=MagicMock(),
    )
    runtime.get_chat_model()

    asyncio.run(runtime.close())
    asyncio.run(runtime.close())

    model.close.assert_called_once_with()
    with pytest.raises(RuntimeError, match="runtime is closed"):
        runtime.get_chat_model()


def test_runtime_isolates_provider_close_failures() -> None:
    failing = MagicMock()
    failing.close.side_effect = RuntimeError("close failed")
    healthy = MagicMock()
    runtime = ApplicationModelProviderRuntime(
        chat_factory=MagicMock(side_effect=[failing, healthy]),
        embedding_factory=MagicMock(),
    )
    runtime.get_chat_model()
    runtime.get_chat_model(0)

    with patch(
        "backend.app.services.runtime_provider.runtime.logger.exception"
    ) as log:
        asyncio.run(runtime.close())

    log.assert_called_once()
    healthy.close.assert_called_once_with()


def test_runtime_accepts_async_resource_close() -> None:
    model = MagicMock()
    model.aclose = AsyncMock()
    runtime = ApplicationModelProviderRuntime(
        chat_factory=MagicMock(return_value=model),
        embedding_factory=MagicMock(),
    )
    runtime.get_chat_model()

    asyncio.run(runtime.close())

    model.aclose.assert_awaited_once_with()
