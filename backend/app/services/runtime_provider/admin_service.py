from __future__ import annotations

"""Administrative runtime model configuration commands."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Mapping

from backend.app.repositories.runtime_provider_repository import (
    RuntimeProviderSettingManager,
)
from backend.app.services.runtime_provider.control_plane import (
    RuntimeProviderUpdate,
    SafeProviderProjection,
    project_provider_config,
)


class RuntimeProviderAdminService:
    def __init__(
        self,
        settings: RuntimeProviderSettingManager,
        *,
        invalidate_models: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._settings = settings
        self._invalidate_models = invalidate_models

    async def get_config(self) -> SafeProviderProjection:
        row = await asyncio.to_thread(self._settings.get_runtime_provider_setting)
        return project_provider_config(row, fallback_provider="openai")

    async def update_config(
        self,
        values: Mapping[str, Any],
    ) -> SafeProviderProjection:
        update = RuntimeProviderUpdate.from_values(
            provider=str(values.get("provider") or ""),
            base_url=str(values.get("base_url") or ""),
            api_key=values.get("api_key"),
            clear_api_key=bool(values.get("clear_api_key", False)),
            model_name=str(values.get("model_name") or ""),
            reasoning_effort=str(values.get("reasoning_effort") or ""),
        )
        row = await asyncio.to_thread(
            self._settings.upsert_runtime_provider_setting,
            update.provider,
            update.base_url,
            values.get("api_key"),
            update.clear_api_key,
            update.model_name,
            update.reasoning_effort,
        )
        if self._invalidate_models is not None:
            await self._invalidate_models()
        return project_provider_config(row, fallback_provider=update.provider)
