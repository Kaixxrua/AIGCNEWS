from __future__ import annotations

from typing import Any, Protocol


class RuntimeProviderSettingReader(Protocol):
    """Read internal runtime model settings that may contain an API key."""

    def get_runtime_provider_setting(
        self,
        provider: str = "",
    ) -> dict[str, Any] | None: ...


class RuntimeProviderSettingManager(RuntimeProviderSettingReader, Protocol):
    """Replace the singleton runtime model setting without exposing its secret."""

    def upsert_runtime_provider_setting(
        self,
        provider: str,
        base_url: str = "",
        api_key: str | None = None,
        clear_api_key: bool = False,
        model_name: str = "",
        reasoning_effort: str = "",
    ) -> dict[str, Any]: ...


class RuntimeProviderSettingRepository(RuntimeProviderSettingManager, Protocol):
    """Combined runtime model setting persistence boundary."""
