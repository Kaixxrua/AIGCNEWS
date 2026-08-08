from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

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
                "reasoning_effort": " High ",
            }
        )
    )

    repository.upsert_runtime_provider_setting.assert_called_once_with(
        "anthropic",
        "https://example.test",
        "",
        True,
        "example-model",
        "high",
    )
    assert projection.provider == "anthropic"
    assert projection.api_key_configured is False


def test_get_enrichment_config_projects_configured_and_effective_effort() -> None:
    repository = MagicMock()
    repository.get_runtime_provider_setting.return_value = {
        "provider": "openai",
        "reasoning_effort": "low",
        "enrichment_reasoning_effort": " High ",
    }
    service = RuntimeProviderAdminService(repository)

    projection = asyncio.run(service.get_enrichment_config())

    assert projection == {
        "reasoning_effort": "high",
        "effective_reasoning_effort": "high",
    }
    repository.get_runtime_provider_setting.assert_called_once_with()


def test_get_enrichment_config_effective_falls_back_to_provider_then_medium() -> None:
    repository = MagicMock()
    repository.get_runtime_provider_setting.return_value = {
        "provider": "openai",
        "reasoning_effort": "low",
        "enrichment_reasoning_effort": "",
    }
    service = RuntimeProviderAdminService(repository)

    assert asyncio.run(service.get_enrichment_config())["effective_reasoning_effort"] == "low"

    repository.get_runtime_provider_setting.return_value = None
    assert (
        asyncio.run(service.get_enrichment_config())["effective_reasoning_effort"]
        == "medium"
    )


def test_update_enrichment_config_normalizes_and_does_not_invalidate_models() -> None:
    repository = MagicMock()
    repository.update_enrichment_reasoning_effort.return_value = {
        "provider": "openai",
        "reasoning_effort": "low",
        "enrichment_reasoning_effort": "minimal",
    }
    invalidate = MagicMock()
    service = RuntimeProviderAdminService(repository, invalidate_models=invalidate)

    projection = asyncio.run(
        service.update_enrichment_config({"reasoning_effort": " Minimal "})
    )

    repository.update_enrichment_reasoning_effort.assert_called_once_with("minimal")
    # 富化推理强度以显式参数下发（缓存键随取值变化），无需重建模型缓存
    invalidate.assert_not_called()
    assert projection == {
        "reasoning_effort": "minimal",
        "effective_reasoning_effort": "minimal",
    }


def _configured_repository() -> MagicMock:
    repository = MagicMock()
    repository.get_runtime_provider_setting.return_value = {
        "provider": "openai",
        "base_url": "https://example.test",
        "model_name": "example-model",
        "api_key": "internal-secret-key",
    }
    return repository


def test_test_connection_succeeds_with_real_model_path() -> None:
    repository = _configured_repository()
    llm = MagicMock()
    llm.invoke.return_value = "pong"
    service = RuntimeProviderAdminService(repository)

    with patch(
        "backend.app.core.model_factory.get_chat_model", return_value=llm
    ) as factory:
        result = asyncio.run(service.test_connection())

    assert result["status"] == "success"
    assert result["provider"] == "openai"
    assert result["base_url"] == "https://example.test"
    assert result["model_name"] == "example-model"
    assert isinstance(result["latency_ms"], int)
    factory.assert_called_once_with(temperature=0)
    llm.invoke.assert_called_once_with("ping，请只回复 pong")


def test_test_connection_short_circuits_when_api_key_missing() -> None:
    repository = MagicMock()
    repository.get_runtime_provider_setting.return_value = {
        "provider": "openai",
        "base_url": "https://example.test",
        "model_name": "example-model",
        "api_key": "",
    }
    service = RuntimeProviderAdminService(repository)

    with patch("backend.app.core.model_factory.get_chat_model") as factory:
        result = asyncio.run(service.test_connection())

    assert result["status"] == "failed"
    assert "API Key" in result["message"]
    assert result["latency_ms"] is None
    factory.assert_not_called()


def test_test_connection_reports_underlying_error_trimmed() -> None:
    repository = _configured_repository()
    llm = MagicMock()
    llm.invoke.side_effect = RuntimeError("x" * 500)
    service = RuntimeProviderAdminService(repository)

    with patch("backend.app.core.model_factory.get_chat_model", return_value=llm):
        result = asyncio.run(service.test_connection())

    assert result["status"] == "failed"
    assert result["message"].startswith("连接测试失败：RuntimeError: ")
    # 原文 500 字符被截到 300，避免超长错误灌进响应
    assert len(result["message"]) == len("连接测试失败：RuntimeError: ") + 300
    assert result["latency_ms"] is None


def test_test_connection_times_out_promptly() -> None:
    repository = _configured_repository()
    llm = MagicMock()
    llm.invoke.side_effect = lambda _prompt: time.sleep(1.0)
    service = RuntimeProviderAdminService(repository)

    with (
        patch("backend.app.core.model_factory.get_chat_model", return_value=llm),
        patch(
            "backend.app.services.runtime_provider.admin_service._TEST_TIMEOUT_SECONDS",
            0.05,
        ),
    ):
        # 注意：asyncio.run 收尾时会 join 默认 executor 线程，elapsed 不反映业务耗时，
        # 超时路径只能由 status/message 证明（wait_for 在 0.05s 触发 TimeoutError）。
        result = asyncio.run(service.test_connection())

    assert result["status"] == "failed"
    assert "超时" in result["message"]
    assert result["latency_ms"] is None
