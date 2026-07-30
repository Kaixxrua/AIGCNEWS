from __future__ import annotations

"""Administrative runtime model configuration commands."""

import asyncio
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
    def __init__(self, settings: RuntimeProviderSettingManager) -> None:
        self._settings = settings

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
        )
        row = await asyncio.to_thread(
            self._settings.upsert_runtime_provider_setting,
            update.provider,
            update.base_url,
            values.get("api_key"),
            update.clear_api_key,
            update.model_name,
        )
        return project_provider_config(row, fallback_provider=update.provider)
