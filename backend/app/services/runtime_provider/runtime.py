from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# 配置保存触发的 invalidate 延迟关闭旧客户端的宽限期：
# 在途调用（富化/简报/翻译线程）仍持有被摘除缓存的客户端引用，
# 同步关闭会让它们以 "Cannot send a request, as the client has been
# closed" 失败（SDK 会包装成误导性的 APIConnectionError）。
_INVALIDATE_CLOSE_DELAY_SECONDS = 300.0


class ApplicationModelProviderRuntime:
    """Own and reuse model providers for the application lifetime."""

    def __init__(
        self,
        *,
        chat_factory: Callable[[float | None, str | None], Any],
        embedding_factory: Callable[[], Any],
        invalidate_close_delay: float = _INVALIDATE_CLOSE_DELAY_SECONDS,
    ) -> None:
        self._chat_factory = chat_factory
        self._embedding_factory = embedding_factory
        self._invalidate_close_delay = invalidate_close_delay
        self._chat_models: dict[tuple[float | None, str | None], Any] = {}
        self._embedding_model: Any | None = None
        self._lock = threading.Lock()
        self._closed = False

    def get_chat_model(
        self,
        temperature: float | None = None,
        reasoning_effort: str | None = None,
    ) -> Any:
        with self._lock:
            self._ensure_open()
            key = (temperature, reasoning_effort)
            if key not in self._chat_models:
                self._chat_models[key] = self._chat_factory(
                    temperature, reasoning_effort
                )
            return self._chat_models[key]

    def get_embedding_model(self) -> Any:
        with self._lock:
            self._ensure_open()
            if self._embedding_model is None:
                self._embedding_model = self._embedding_factory()
            return self._embedding_model

    async def invalidate(self) -> None:
        with self._lock:
            self._ensure_open()
            providers = self._detach_providers()
        if self._invalidate_close_delay <= 0:
            await self._close_providers(providers)
            return
        # 立即摘除缓存保证新请求拿到新配置；旧客户端延迟关闭，
        # 给仍持有旧客户端的在途请求留宽限期，避免误杀在途调用。
        loop = asyncio.get_running_loop()
        loop.call_later(
            self._invalidate_close_delay,
            self._schedule_close,
            loop,
            providers,
        )

    async def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            providers = self._detach_providers()
        await self._close_providers(providers)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("Application model provider runtime is closed")

    def _detach_providers(self) -> tuple[Any, ...]:
        providers = tuple(self._chat_models.values())
        if self._embedding_model is not None:
            providers += (self._embedding_model,)
        self._chat_models.clear()
        self._embedding_model = None
        return providers

    def _schedule_close(
        self,
        loop: asyncio.AbstractEventLoop,
        providers: tuple[Any, ...],
    ) -> None:
        if loop.is_closed():
            return
        loop.create_task(self._close_providers(providers))

    async def _close_providers(self, providers: tuple[Any, ...]) -> None:
        closed_resources: set[int] = set()
        for provider in providers:
            for resource in self._owned_resources(provider):
                identity = id(resource)
                if identity in closed_resources:
                    continue
                closed_resources.add(identity)
                try:
                    await self._close_resource(resource)
                except Exception:
                    logger.exception(
                        "Model provider resource close failed: %s",
                        type(resource).__name__,
                    )

    @staticmethod
    def _owned_resources(provider: Any) -> tuple[Any, ...]:
        attributes = vars(provider) if hasattr(provider, "__dict__") else {}
        resources: list[Any] = []
        for name in (
            "http_client",
            "http_async_client",
            "client",
            "async_client",
            "_client",
            "_async_client",
        ):
            resource = attributes.get(name)
            if resource is not None and resource is not provider:
                resources.append(resource)
        return tuple(resources) or (provider,)

    @staticmethod
    async def _close_resource(resource: Any) -> None:
        async_close = getattr(resource, "aclose", None)
        if async_close is not None and inspect.iscoroutinefunction(async_close):
            await async_close()
            return
        close = getattr(resource, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result
            return
        if async_close is not None:
            result = async_close()
            if inspect.isawaitable(result):
                await result
