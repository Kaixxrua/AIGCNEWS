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

    def chat_factory(
        temperature: float | None,
        reasoning_effort: str | None = None,
    ) -> object:
        model = (temperature, reasoning_effort, object())
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
    assert runtime.get_chat_model(0, "medium") is runtime.get_chat_model(0, "medium")
    assert runtime.get_chat_model(0) is not runtime.get_chat_model(0, "medium")
    assert runtime.get_embedding_model() is runtime.get_embedding_model()
    assert len(chats) == 3
    assert len(embeddings) == 1


def test_runtime_invalidation_with_zero_delay_closes_detached_resources() -> None:
    chat_client = MagicMock()
    chat = MagicMock(client=chat_client)
    embedding_client = MagicMock()
    embedding = MagicMock(http_client=embedding_client)
    runtime = ApplicationModelProviderRuntime(
        chat_factory=MagicMock(return_value=chat),
        embedding_factory=MagicMock(return_value=embedding),
        invalidate_close_delay=0,
    )

    assert runtime.get_chat_model() is chat
    assert runtime.get_embedding_model() is embedding
    asyncio.run(runtime.invalidate())

    chat_client.close.assert_called_once_with()
    embedding_client.close.assert_called_once_with()
    assert runtime.get_chat_model() is chat


def test_runtime_invalidation_defers_detached_provider_close() -> None:
    # 默认宽限期内旧客户端不得被关闭：在途请求（富化/简报/翻译）
    # 仍持有旧客户端引用，同步关闭会把它们打成 APIConnectionError。
    chat_client = MagicMock()
    old_chat = MagicMock(client=chat_client)
    new_chat = MagicMock()
    runtime = ApplicationModelProviderRuntime(
        chat_factory=MagicMock(side_effect=[old_chat, new_chat]),
        embedding_factory=MagicMock(),
    )

    assert runtime.get_chat_model() is old_chat
    asyncio.run(runtime.invalidate())

    chat_client.close.assert_not_called()
    # 缓存已立即摘除，下一次取模型走工厂拿到新配置构建的实例
    assert runtime.get_chat_model() is new_chat
    # 在途方持有的旧实例引用依旧可用（未被关闭）
    chat_client.close.assert_not_called()


def test_runtime_deferred_invalidation_close_runs_after_delay() -> None:
    async def scenario() -> MagicMock:
        chat_client = MagicMock()
        chat = MagicMock(client=chat_client)
        runtime = ApplicationModelProviderRuntime(
            chat_factory=MagicMock(return_value=chat),
            embedding_factory=MagicMock(),
            invalidate_close_delay=0.05,
        )
        assert runtime.get_chat_model() is chat
        await runtime.invalidate()
        chat_client.close.assert_not_called()
        await asyncio.sleep(0.2)
        return chat_client

    chat_client = asyncio.run(scenario())

    chat_client.close.assert_called_once_with()


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
