from __future__ import annotations

import inspect
import logging
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


class ApplicationModelProviderRuntime:
    """Own and reuse model providers for the application lifetime."""

    def __init__(
        self,
        *,
        chat_factory: Callable[[float | None], Any],
        embedding_factory: Callable[[], Any],
    ) -> None:
        self._chat_factory = chat_factory
        self._embedding_factory = embedding_factory
        self._chat_models: dict[float | None, Any] = {}
        self._embedding_model: Any | None = None
        self._lock = threading.Lock()
        self._closed = False

    def get_chat_model(self, temperature: float | None = None) -> Any:
        with self._lock:
            self._ensure_open()
            if temperature not in self._chat_models:
                self._chat_models[temperature] = self._chat_factory(temperature)
            return self._chat_models[temperature]

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
        await self._close_providers(providers)

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
