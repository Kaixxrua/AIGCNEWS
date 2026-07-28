from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

OPENAI_PROVIDER = "openai"
OLLAMA_PROVIDER = "ollama"
ANTHROPIC_PROVIDER = "anthropic"


@dataclass(frozen=True, slots=True)
class RuntimeProviderConfig:
    provider: str
    base_url: str
    model_name: str
    api_key: str | None

    @classmethod
    def from_row(
        cls,
        row: Mapping[str, Any] | None,
        *,
        fallback_provider: str = OPENAI_PROVIDER,
    ) -> RuntimeProviderConfig:
        return cls(
            provider=normalize_provider(
                row.get("provider") if row else None,
                fallback=fallback_provider,
            ),
            base_url=_text(row.get("base_url") if row else None),
            model_name=_text(row.get("model_name") if row else None),
            api_key=_optional_text(row.get("api_key") if row else None),
        )


@dataclass(frozen=True, slots=True)
class RuntimeProviderUpdate:
    provider: str
    base_url: str = ""
    api_key: str | None = None
    clear_api_key: bool = False
    model_name: str = ""

    @classmethod
    def from_values(
        cls,
        *,
        provider: str,
        base_url: str = "",
        api_key: str | None = None,
        clear_api_key: bool = False,
        model_name: str = "",
    ) -> RuntimeProviderUpdate:
        return cls(
            provider=normalize_provider(provider),
            base_url=_text(base_url),
            api_key=_optional_text(api_key),
            clear_api_key=clear_api_key,
            model_name=_text(model_name),
        )


@dataclass(frozen=True, slots=True)
class SafeProviderProjection:
    provider: str
    base_url: str
    model_name: str
    api_key_configured: bool
    api_key_masked: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class EffectiveChatConfig:
    provider: str
    api_key: str | None
    base_url: str | None
    model_name: str
    temperature: float


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_text(value: Any) -> str | None:
    normalized = _text(value)
    return normalized or None


def normalize_provider(
    value: Any,
    *,
    fallback: str = OLLAMA_PROVIDER,
) -> str:
    normalized = _text(value).lower()
    return normalized or fallback


def effective_value(
    row: Mapping[str, Any] | None,
    key: str,
    fallback: str | None,
) -> str | None:
    value = _optional_text(row.get(key) if row else None)
    return value or fallback


def effective_model_name(
    row: Mapping[str, Any] | None,
    fallback: str,
) -> str:
    return effective_value(row, "model_name", fallback) or fallback


def resolve_chat_config(
    row: Mapping[str, Any] | None,
    *,
    fallback_provider: str,
    fallback_api_key: str | None,
    fallback_base_url: str | None,
    fallback_model_name: str,
    fallback_temperature: float,
    temperature: float | None = None,
) -> EffectiveChatConfig:
    return EffectiveChatConfig(
        provider=normalize_provider(
            row.get("provider") if row else None,
            fallback=normalize_provider(fallback_provider),
        ),
        api_key=effective_value(row, "api_key", fallback_api_key),
        base_url=effective_value(row, "base_url", fallback_base_url),
        model_name=effective_model_name(row, fallback_model_name),
        temperature=temperature if temperature is not None else fallback_temperature,
    )


def mask_api_key(api_key: str | None) -> str | None:
    if not api_key:
        return None
    if len(api_key) <= 8:
        return "****"
    return f"{api_key[:4]}****{api_key[-4:]}"


def project_provider_config(
    row: Mapping[str, Any] | None,
    *,
    fallback_provider: str = OPENAI_PROVIDER,
) -> SafeProviderProjection:
    config = RuntimeProviderConfig.from_row(
        row,
        fallback_provider=fallback_provider,
    )
    updated_at = row.get("updated_at") if row else None
    if isinstance(updated_at, datetime):
        updated_at_value = str(updated_at)
    else:
        updated_at_value = str(updated_at) if updated_at else None
    return SafeProviderProjection(
        provider=config.provider,
        base_url=config.base_url,
        model_name=config.model_name,
        api_key_configured=bool(config.api_key),
        api_key_masked=mask_api_key(config.api_key),
        updated_at=updated_at_value,
    )
