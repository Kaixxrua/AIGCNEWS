from __future__ import annotations

from typing import Any, Optional

from langchain_ollama import ChatOllama, OllamaEmbeddings

from backend.app.core.config import settings
from backend.app.services.runtime_provider.adapters import (
    ProviderConstructors,
    RuntimeSettingSource,
)
from backend.app.services.runtime_provider.control_plane import (
    effective_value,
    normalize_provider,
    resolve_chat_config,
)


OPENAI_PROVIDER = "openai"
OLLAMA_PROVIDER = "ollama"
ANTHROPIC_PROVIDER = "anthropic"
HUGGINGFACE_PROVIDER = "huggingface"


def _resolve_provider(preferred: str | None) -> str:
    fallback = getattr(settings, "llm_provider", "") or OLLAMA_PROVIDER
    return normalize_provider(preferred, fallback=fallback)


def _get_runtime_provider_setting_reader():
    from backend.app.repositories.application_repository_context import (
        get_configured_application_repositories,
    )

    return get_configured_application_repositories().runtime_provider_settings


def _get_runtime_provider_setting(provider: str | None = None) -> dict[str, Any]:
    """读取运维页保存的唯一运行时模型配置；失败时静默回退到 .env。"""
    return RuntimeSettingSource(_get_runtime_provider_setting_reader).read(provider)


def _openai_chat_type():
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError("LLM_PROVIDER=openai 需要安装 langchain-openai。") from exc
    ChatOpenAI._use_responses_api = lambda self, kwargs: False  # type: ignore[attr-defined]
    return ChatOpenAI


def _anthropic_chat_type():
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as exc:
        raise RuntimeError(
            "LLM_PROVIDER=anthropic 需要安装 langchain-anthropic：pip install langchain-anthropic"
        ) from exc
    return ChatAnthropic


def _openai_embeddings_type():
    try:
        from langchain_openai import OpenAIEmbeddings
    except ImportError as exc:
        raise RuntimeError(
            "EMBEDDING_PROVIDER=openai 需要安装 langchain-openai：pip install langchain-openai"
        ) from exc
    return OpenAIEmbeddings


def _huggingface_embeddings_type():
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
    except ImportError as exc:
        raise RuntimeError(
            "EMBEDDING_PROVIDER=huggingface 需要安装 langchain-huggingface：pip install langchain-huggingface"
        ) from exc
    return HuggingFaceEmbeddings


def _provider_constructors() -> ProviderConstructors:
    return ProviderConstructors(
        openai_chat=_openai_chat_type,
        anthropic_chat=_anthropic_chat_type,
        ollama_chat=ChatOllama,
        openai_embeddings=_openai_embeddings_type,
        huggingface_embeddings=_huggingface_embeddings_type,
        ollama_embeddings=OllamaEmbeddings,
    )


def get_chat_model(temperature: float | None = None):
    """
    根据运维页保存的运行时配置（优先）或 settings.LLM_PROVIDER 返回对应的 Chat 模型实例。

    支持的 provider：
    - openai    使用 ChatOpenAI（OpenAI 官方或兼容代理）
    - anthropic 使用 ChatAnthropic 原生 SDK（支持 Extended Thinking / 流式思维链）
    - ollama    使用 ChatOllama 本地模型

    可传入 temperature 覆盖 settings 中的默认值。
    """
    runtime_config = _get_runtime_provider_setting()
    resolved = resolve_chat_config(
        runtime_config,
        fallback_provider=settings.llm_provider,
        fallback_api_key=settings.openai_api_key,
        fallback_base_url=settings.openai_base_url or None,
        fallback_model_name=settings.chat_model_name,
        fallback_temperature=settings.llm_temperature,
        temperature=temperature,
    )
    provider = resolved.provider
    constructors = _provider_constructors()

    # ── Anthropic 原生 API ───────────────────────────────────────────────
    if provider == ANTHROPIC_PROVIDER:
        init_kwargs: dict = dict(
            api_key=effective_value(
                runtime_config,
                "api_key",
                settings.anthropic_api_key or settings.openai_api_key,
            ),
            model=resolved.model_name,
            temperature=resolved.temperature,
            max_tokens=settings.llm_max_tokens,
            streaming=True,
        )

        # 代理端点（可选）
        anthropic_base_url = effective_value(
            runtime_config, "base_url", settings.anthropic_base_url or None
        )
        if anthropic_base_url:
            init_kwargs["base_url"] = anthropic_base_url

        # Extended Thinking（budget > 0 时启用）
        if settings.anthropic_thinking_budget > 0:
            init_kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": settings.anthropic_thinking_budget,
            }
            # Extended Thinking 要求 temperature=1，强制覆盖
            init_kwargs["temperature"] = 1

        return constructors.create_anthropic_chat(init_kwargs)

    # ── OpenAI / 兼容代理 ───────────────────────────────────────────────
    if provider == OPENAI_PROVIDER:
        return constructors.create_openai_chat(
            {
                "api_key": resolved.api_key,
                "base_url": resolved.base_url,
                "model": resolved.model_name,
                "temperature": resolved.temperature,
                "max_tokens": settings.llm_max_tokens,
                "streaming": True,
                "max_retries": 2,
            }
        )

    # ── Ollama 本地模型 ─────────────────────────────────────────────────
    return constructors.create_ollama_chat(
        {
            "base_url": settings.ollama_base_url,
            "model": settings.chat_model_name,
            "temperature": resolved.temperature,
        }
    )


def get_embedding_model():
    """
    根据配置返回对应的 Embeddings 实例。

    支持的 provider：
    - openai      使用 OpenAIEmbeddings（需代理支持 /v1/embeddings）
    - huggingface 使用 HuggingFaceEmbeddings（本地 sentence-transformers，无需外部 API）
    - ollama      使用 OllamaEmbeddings（本地 Ollama 服务）
    """
    provider = _resolve_provider(settings.embedding_provider)
    constructors = _provider_constructors()

    if provider == OPENAI_PROVIDER:
        # Embedding 支持独立的 API Key / Base URL（留空则复用 LLM 的 OpenAI 配置）
        runtime_config = _get_runtime_provider_setting(OPENAI_PROVIDER)
        emb_base_url = settings.embedding_base_url or effective_value(
            runtime_config, "base_url", settings.openai_base_url or None
        )
        siliconflow_key = (
            settings.siliconflow_api_key
            if emb_base_url and "siliconflow." in emb_base_url.lower()
            else ""
        )
        emb_api_key = settings.embedding_api_key or siliconflow_key or effective_value(
            runtime_config, "api_key", settings.openai_api_key
        )

        embedding_http_client = None
        if emb_base_url and "siliconflow." in emb_base_url.lower():
            import httpx

            embedding_http_client = httpx.Client(trust_env=False)

        return constructors.create_openai_embeddings(
            {
                "api_key": emb_api_key,
                "base_url": emb_base_url,
                "model": settings.embedding_model_name,
                "http_client": embedding_http_client,
                "tiktoken_enabled": embedding_http_client is None,
                "check_embedding_ctx_length": embedding_http_client is None,
            }
        )

    if provider == HUGGINGFACE_PROVIDER:
        import os

        # 优先使用 hf-mirror.com 镜像（国内服务器访问 huggingface.co 不通）
        if not os.environ.get("HF_ENDPOINT"):
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

        # 强制离线加载：模型已在本地缓存，禁止网络请求
        # 新版 sentence-transformers 会检查 adapter_config.json（PEFT 适配器）
        # 设置 TRANSFORMERS_OFFLINE=1 / HF_HUB_OFFLINE=1 阻止任何网络请求
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["HF_HUB_OFFLINE"] = "1"

        return constructors.create_huggingface_embeddings(
            {
                "model_name": settings.embedding_model_name,
                "model_kwargs": {"device": "cpu", "local_files_only": True},
                "encode_kwargs": {"normalize_embeddings": True},
            }
        )

    # 默认 Ollama
    return constructors.create_ollama_embeddings(
        {
            "base_url": settings.ollama_base_url,
            "model": settings.embedding_model_name,
        }
    )
