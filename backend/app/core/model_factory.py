from __future__ import annotations

from langchain_ollama import ChatOllama, OllamaEmbeddings

from backend.app.core.config import settings


OPENAI_PROVIDER = "openai"
OLLAMA_PROVIDER = "ollama"
ANTHROPIC_PROVIDER = "anthropic"


def _resolve_provider(preferred: str | None) -> str:
    provider = (preferred or "").strip().lower()
    if not provider:
        provider = settings.llm_provider
    return provider or OLLAMA_PROVIDER


def get_chat_model(temperature: float | None = None):
    """
    根据 settings.LLM_PROVIDER 返回对应的 Chat 模型实例。

    支持的 provider：
    - openai    使用 ChatOpenAI（OpenAI 官方或兼容代理）
    - anthropic 使用 ChatAnthropic 原生 SDK（支持 Extended Thinking / 流式思维链）
    - ollama    使用 ChatOllama 本地模型

    可传入 temperature 覆盖 settings 中的默认值。
    """
    provider = _resolve_provider(settings.llm_provider)
    effective_temperature = (
        temperature if temperature is not None else settings.llm_temperature
    )

    # ── Anthropic 原生 API ───────────────────────────────────────────────
    if provider == ANTHROPIC_PROVIDER:
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError as exc:
            raise RuntimeError(
                "LLM_PROVIDER=anthropic 需要安装 langchain-anthropic：pip install langchain-anthropic"
            ) from exc

        init_kwargs: dict = dict(
            api_key=settings.anthropic_api_key or settings.openai_api_key,
            model=settings.chat_model_name,
            temperature=effective_temperature,
            max_tokens=settings.llm_max_tokens,
            streaming=True,
        )

        # 代理端点（可选）
        if settings.anthropic_base_url:
            init_kwargs["base_url"] = settings.anthropic_base_url

        # Extended Thinking（budget > 0 时启用）
        if settings.anthropic_thinking_budget > 0:
            init_kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": settings.anthropic_thinking_budget,
            }
            # Extended Thinking 要求 temperature=1，强制覆盖
            init_kwargs["temperature"] = 1

        return ChatAnthropic(**init_kwargs)

    # ── OpenAI / 兼容代理 ───────────────────────────────────────────────
    if provider == OPENAI_PROVIDER:
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError(
                "LLM_PROVIDER=openai 需要安装 langchain-openai。"
            ) from exc

        # 强制使用旧版 /v1/chat/completions endpoint，兼容代理 API
        try:
            ChatOpenAI._use_responses_api = lambda self, kwargs: False  # type: ignore[attr-defined]
        except Exception:
            pass

        return ChatOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
            model=settings.chat_model_name,
            temperature=effective_temperature,
            max_tokens=settings.llm_max_tokens,
            streaming=True,
            max_retries=2,
        )

    # ── Ollama 本地模型 ─────────────────────────────────────────────────
    return ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.chat_model_name,
        temperature=effective_temperature,
    )


def get_embedding_model():
    """
    根据配置返回 OllamaEmbeddings 或 OpenAIEmbeddings。
    """
    provider = _resolve_provider(settings.embedding_provider)
    if provider == OPENAI_PROVIDER:
        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError as exc:
            raise RuntimeError(
                "EMBEDDING_PROVIDER=openai 需要安装 langchain-openai。"
            ) from exc

        return OpenAIEmbeddings(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
            model=settings.embedding_model_name,
        )

    return OllamaEmbeddings(
        base_url=settings.ollama_base_url,
        model=settings.embedding_model_name,
    )
