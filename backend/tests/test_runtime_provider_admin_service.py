from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from backend.app.services.runtime_provider.admin_service import (
    RuntimeProviderAdminService,
)


def test_get_config_projects_safe_default_and_redacts_secret() -> None:
    repository = MagicMock()
    repository.get_runtime_provider_setting.return_value = {
        "provider": "anthropic",
        "base_url": "https://example.test",
        "model_name": "example-model",
        "api_key": "internal-secret-key",
    }
    service = RuntimeProviderAdminService(repository)

    projection = asyncio.run(service.get_config())

    assert projection.provider == "anthropic"
    assert projection.api_key_configured is True
    assert projection.api_key_masked == "inte****-key"
    assert not hasattr(projection, "api_key")
    repository.get_runtime_provider_setting.assert_called_once_with()


def test_update_config_invalidates_models_after_persistence() -> None:
    repository = MagicMock()
    repository.upsert_runtime_provider_setting.return_value = {
        "provider": "openai",
        "base_url": "https://example.test",
        "model_name": "example-model",
        "api_key": None,
    }
    events: list[str] = []

    async def invalidate() -> None:
        events.append("invalidate")

    service = RuntimeProviderAdminService(repository, invalidate_models=invalidate)
    asyncio.run(service.update_config({"provider": "openai"}))

    assert events == ["invalidate"]
    repository.upsert_runtime_provider_setting.assert_called_once()


def test_update_config_does_not_invalidate_when_persistence_fails() -> None:
    repository = MagicMock()
    repository.upsert_runtime_provider_setting.side_effect = RuntimeError("write failed")
    invalidate = MagicMock()
    service = RuntimeProviderAdminService(repository, invalidate_models=invalidate)

    with pytest.raises(RuntimeError, match="write failed"):
        asyncio.run(service.update_config({"provider": "openai"}))

    invalidate.assert_not_called()


def test_update_config_normalizes_fields_and_preserves_raw_key_intent() -> None:
    repository = MagicMock()
    repository.upsert_runtime_provider_setting.return_value = {
        "provider": "anthropic",
        "base_url": "https://example.test",
        "model_name": "example-model",
        "api_key": None,
    }
    service = RuntimeProviderAdminService(repository)

    projection = asyncio.run(
        service.update_config(
            {
                "provider": " Anthropic ",
                "base_url": " https://example.test ",
                "model_name": " example-model ",
                "api_key": "",
                "clear_api_key": True,
            }
        )
    )

    repository.upsert_runtime_provider_setting.assert_called_once_with(
        "anthropic",
        "https://example.test",
        "",
        True,
        "example-model",
    )
    assert projection.provider == "anthropic"
    assert projection.api_key_configured is False
