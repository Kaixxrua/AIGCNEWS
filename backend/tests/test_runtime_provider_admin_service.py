from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from backend.app.services.outbound_target_policy import OutboundTargetPolicyError
from backend.app.services.runtime_provider import admin_service
from backend.app.services.runtime_provider.admin_service import (
    InvalidProviderBaseUrl,
    RuntimeProviderAdminService,
    _classify_test_failure,
    validate_admin_base_url,
)


def _public_resolver(_hostname: str) -> tuple[str, ...]:
    return ("93.184.216.34",)


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
        "base_url": "https://example.test/",
        "model_name": "example-model",
        "api_key": None,
    }
    service = RuntimeProviderAdminService(repository)

    with patch.object(
        admin_service, "resolve_public_ips", side_effect=_public_resolver
    ):
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
        "https://example.test/",
        "",
        True,
        "example-model",
        "high",
    )
    assert projection.provider == "anthropic"
    assert projection.api_key_configured is False


def test_update_config_rejects_unsafe_base_url_targets_before_persistence() -> None:
    # 走真实出站策略（不 patch resolver）：字面量地址短路 DNS，无网络依赖
    repository = MagicMock()
    service = RuntimeProviderAdminService(repository)

    for base_url in (
        "http://169.254.169.254/latest/meta-data",
        "http://127.0.0.1:11434/v1",
        "http://192.168.1.10:8000/v1",
        "http://[::1]/v1",
        "ftp://example.test/v1",
        "https://user:secret@example.test/v1",
    ):
        with pytest.raises(InvalidProviderBaseUrl, match="Base URL 不合法"):
            asyncio.run(
                service.update_config({"provider": "openai", "base_url": base_url})
            )
    repository.upsert_runtime_provider_setting.assert_not_called()


def test_update_config_rejects_unresolvable_base_url_host() -> None:
    repository = MagicMock()
    service = RuntimeProviderAdminService(repository)

    with (
        patch.object(
            admin_service,
            "resolve_public_ips",
            side_effect=OutboundTargetPolicyError("无法解析域名：gone.invalid"),
        ),
        pytest.raises(InvalidProviderBaseUrl, match="无法解析域名"),
    ):
        asyncio.run(
            service.update_config(
                {"provider": "openai", "base_url": "https://gone.invalid/v1"}
            )
        )
    repository.upsert_runtime_provider_setting.assert_not_called()


def test_validate_admin_base_url_normalizes_and_allows_public_hosts() -> None:
    assert validate_admin_base_url("") == ""
    with patch.object(
        admin_service, "resolve_public_ips", side_effect=_public_resolver
    ) as resolver:
        assert validate_admin_base_url("HTTPS://Example.TEST/v1#frag") == (
            "https://example.test/v1"
        )
    resolver.assert_called_once_with("example.test")


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

    with (
        patch(
            "backend.app.core.model_factory.get_chat_model", return_value=llm
        ) as factory,
        patch.object(admin_service, "resolve_public_ips", side_effect=_public_resolver),
    ):
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


def test_test_connection_rejects_legacy_unsafe_base_url_before_model_call() -> None:
    # 本校验上线前落库的 Base URL：连接测试同样不得触达内网（真实策略，字面量短路）
    repository = MagicMock()
    repository.get_runtime_provider_setting.return_value = {
        "provider": "openai",
        "base_url": "http://169.254.169.254/latest/meta-data",
        "model_name": "example-model",
        "api_key": "internal-secret-key",
    }
    service = RuntimeProviderAdminService(repository)

    with patch("backend.app.core.model_factory.get_chat_model") as factory:
        result = asyncio.run(service.test_connection())

    assert result["status"] == "failed"
    assert "Base URL 不合法" in result["message"]
    assert result["latency_ms"] is None
    factory.assert_not_called()


def test_test_connection_never_echoes_raw_exception_text() -> None:
    repository = _configured_repository()
    llm = MagicMock()
    llm.invoke.side_effect = RuntimeError("x" * 500)
    service = RuntimeProviderAdminService(repository)

    with (
        patch("backend.app.core.model_factory.get_chat_model", return_value=llm),
        patch.object(admin_service, "resolve_public_ips", side_effect=_public_resolver),
    ):
        result = asyncio.run(service.test_connection())

    assert result["status"] == "failed"
    # 异常原文与异常类名都不回显（类名可指纹化内部栈），只给分类排查文案
    assert result["message"] == (
        "连接测试失败：请求失败，请检查模型服务配置与网络环境。"
    )
    assert "x" * 500 not in result["message"]
    assert "RuntimeError" not in result["message"]
    assert result["latency_ms"] is None


def test_classify_test_failure_categories() -> None:
    class AuthenticationError(Exception):
        pass

    class APIConnectionError(Exception):
        pass

    class NotFoundError(Exception):
        pass

    class RateLimitError(Exception):
        pass

    assert "鉴权失败" in _classify_test_failure(AuthenticationError("bad key"))
    assert "网络连接失败" in _classify_test_failure(APIConnectionError("boom"))
    assert "模型或接口不存在" in _classify_test_failure(NotFoundError("no model"))
    assert "触发上游限流" in _classify_test_failure(RateLimitError("slow down"))
    assert "请求失败" in _classify_test_failure(RuntimeError("misc"))


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
        patch.object(admin_service, "resolve_public_ips", side_effect=_public_resolver),
    ):
        # 注意：asyncio.run 收尾时会 join 默认 executor 线程，elapsed 不反映业务耗时，
        # 超时路径只能由 status/message 证明（wait_for 在 0.05s 触发 TimeoutError）。
        result = asyncio.run(service.test_connection())

    assert result["status"] == "failed"
    assert "超时" in result["message"]
    assert result["latency_ms"] is None
