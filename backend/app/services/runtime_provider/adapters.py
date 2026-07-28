from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol

from backend.app.repositories.runtime_provider_repository import (
    RuntimeProviderSettingReader,
)


class ChatProviderConstructor(Protocol):
    def __call__(self, **kwargs: Any) -> Any: ...


class EmbeddingProviderConstructor(Protocol):
    def __call__(self, **kwargs: Any) -> Any: ...


class RuntimeSettingSource:
    """Read runtime provider settings while preserving static fallback behavior."""

    def __init__(
        self,
        reader_factory: Callable[[], RuntimeProviderSettingReader],
    ) -> None:
        self._reader_factory = reader_factory

    def read(self, provider: str | None = None) -> dict[str, Any]:
        try:
            row = self._reader_factory().get_runtime_provider_setting(
                provider or ""
            )
        except Exception:
            return {}
        return dict(row) if row else {}


class ProviderConstructors:
    """Keep provider SDK construction lazy and independently injectable."""

    def __init__(
        self,
        *,
        openai_chat: Callable[[], ChatProviderConstructor],
        anthropic_chat: Callable[[], ChatProviderConstructor],
        ollama_chat: ChatProviderConstructor,
        openai_embeddings: Callable[[], EmbeddingProviderConstructor],
        huggingface_embeddings: Callable[[], EmbeddingProviderConstructor],
        ollama_embeddings: EmbeddingProviderConstructor,
    ) -> None:
        self._openai_chat = openai_chat
        self._anthropic_chat = anthropic_chat
        self._ollama_chat = ollama_chat
        self._openai_embeddings = openai_embeddings
        self._huggingface_embeddings = huggingface_embeddings
        self._ollama_embeddings = ollama_embeddings

    def create_openai_chat(self, kwargs: Mapping[str, Any]) -> Any:
        return self._openai_chat()(**dict(kwargs))

    def create_anthropic_chat(self, kwargs: Mapping[str, Any]) -> Any:
        return self._anthropic_chat()(**dict(kwargs))

    def create_ollama_chat(self, kwargs: Mapping[str, Any]) -> Any:
        return self._ollama_chat(**dict(kwargs))

    def create_openai_embeddings(self, kwargs: Mapping[str, Any]) -> Any:
        return self._openai_embeddings()(**dict(kwargs))

    def create_huggingface_embeddings(self, kwargs: Mapping[str, Any]) -> Any:
        return self._huggingface_embeddings()(**dict(kwargs))

    def create_ollama_embeddings(self, kwargs: Mapping[str, Any]) -> Any:
        return self._ollama_embeddings(**dict(kwargs))
