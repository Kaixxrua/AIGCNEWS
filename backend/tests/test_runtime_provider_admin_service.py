from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

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
