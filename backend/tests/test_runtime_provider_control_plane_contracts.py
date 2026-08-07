from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_ops
from backend.app.api.dependencies import get_runtime_provider_setting_repository
from backend.app.core import model_factory
from backend.app.core.auth import RequireAdmin
from backend.app.repositories.runtime_provider_repository import (
    RuntimeProviderSettingManager,
)


def _model_settings(**overrides):
    values = {
        "llm_provider": "ollama",
        "llm_temperature": 0.25,
        "llm_max_tokens": 2048,
        "openai_api_key": "static-openai-key",
        "openai_base_url": "https://static-openai.test/v1",
        "anthropic_api_key": "static-anthropic-key",
        "anthropic_base_url": "https://static-anthropic.test",
        "anthropic_thinking_budget": 0,
        "ollama_base_url": "http://ollama.test:11434",
        "chat_model_name": "static-chat-model",
        "embedding_provider": "openai",
        "embedding_api_key": "",
        "embedding_base_url": "",
        "embedding_model_name": "static-embedding-model",
        "siliconflow_api_key": "",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class RuntimeProviderModelFactoryContracts(unittest.TestCase):
    def test_openai_runtime_values_and_explicit_temperature_reach_constructor(self) -> None:
        runtime = {
            "provider": " OpenAI ",
            "api_key": " runtime-openai-key ",
            "base_url": " https://runtime-openai.test/v1 ",
            "model_name": " runtime-chat-model ",
        }
        model = MagicMock()

        with (
            patch.object(model_factory, "settings", _model_settings()),
            patch.object(
                model_factory,
                "_get_runtime_provider_setting",
                return_value=runtime,
            ) as runtime_reader,
            patch("langchain_openai.ChatOpenAI", return_value=model) as factory,
        ):
            result = model_factory.get_chat_model(temperature=0)

        self.assertIs(result, model)
        runtime_reader.assert_called_once_with()
        factory.assert_called_once_with(
            api_key="runtime-openai-key",
            base_url="https://runtime-openai.test/v1",
            model="runtime-chat-model",
            temperature=0,
            max_tokens=2048,
            streaming=True,
            max_retries=2,
            default_headers={
                "User-Agent": model_factory.COMPATIBLE_RELAY_USER_AGENT
            },
        )
        self.assertFalse(factory._use_responses_api(object(), {}))

    def test_openai_reasoning_effort_reaches_constructor_only_when_set(self) -> None:
        runtime = {
            "provider": "openai",
            "api_key": "runtime-openai-key",
            "base_url": "https://runtime-openai.test/v1",
            "model_name": "runtime-chat-model",
        }

        with (
            patch.object(model_factory, "settings", _model_settings()),
            patch.object(
                model_factory,
                "_get_runtime_provider_setting",
                return_value=runtime,
            ),
            patch("langchain_openai.ChatOpenAI") as factory,
        ):
            model_factory.get_chat_model(temperature=0, reasoning_effort="medium")

        self.assertEqual(factory.call_args.kwargs["reasoning_effort"], "medium")

        with (
            patch.object(model_factory, "settings", _model_settings()),
            patch.object(
                model_factory,
                "_get_runtime_provider_setting",
                return_value=runtime,
            ),
            patch("langchain_openai.ChatOpenAI") as factory,
        ):
            model_factory.get_chat_model(temperature=0)

        self.assertNotIn("reasoning_effort", factory.call_args.kwargs)

    def test_configured_reasoning_effort_applies_when_caller_omits_it(self) -> None:
        runtime = {
            "provider": "openai",
            "api_key": "runtime-openai-key",
            "base_url": "https://runtime-openai.test/v1",
            "model_name": "runtime-chat-model",
            "reasoning_effort": "high",
        }

        with (
            patch.object(model_factory, "settings", _model_settings()),
            patch.object(
                model_factory,
                "_get_runtime_provider_setting",
                return_value=runtime,
            ),
            patch("langchain_openai.ChatOpenAI") as factory,
        ):
            model_factory.get_chat_model(temperature=0)

        self.assertEqual(factory.call_args.kwargs["reasoning_effort"], "high")

        with (
            patch.object(model_factory, "settings", _model_settings()),
            patch.object(
                model_factory,
                "_get_runtime_provider_setting",
                return_value=runtime,
            ),
            patch("langchain_openai.ChatOpenAI") as factory,
        ):
            model_factory.get_chat_model(temperature=0, reasoning_effort="low")

        self.assertEqual(factory.call_args.kwargs["reasoning_effort"], "low")

    def test_get_configured_reasoning_effort_reads_runtime_row(self) -> None:
        with patch.object(
            model_factory,
            "_get_runtime_provider_setting",
            return_value={"reasoning_effort": " Low "},
        ):
            self.assertEqual(model_factory.get_configured_reasoning_effort(), "low")

        with patch.object(
            model_factory,
            "_get_runtime_provider_setting",
            return_value={},
        ):
            self.assertIsNone(model_factory.get_configured_reasoning_effort())
            self.assertEqual(
                model_factory.get_configured_reasoning_effort(fallback="medium"),
                "medium",
            )

    def test_enricher_llm_uses_configured_reasoning_effort_with_medium_fallback(self) -> None:
        from backend.app.services.ingestion import (
            github_project_enricher as enricher_module,
        )

        reader = SimpleNamespace(
            get_runtime_provider_setting=lambda: {"reasoning_effort": "high"}
        )
        db = SimpleNamespace(runtime_provider_settings=reader)
        enricher = enricher_module.GitHubProjectEnricher(db)

        with (
            patch.object(
                enricher_module,
                "get_configured_reasoning_effort",
                return_value="high",
            ) as configured,
            patch.object(enricher_module, "get_chat_model") as get_model,
        ):
            _ = enricher.llm
            _ = enricher.llm

        configured.assert_called_once_with(fallback="medium")
        get_model.assert_called_once_with(temperature=0, reasoning_effort="high")

    def test_blank_runtime_values_fall_back_to_static_openai_settings(self) -> None:
        runtime = {
            "provider": "openai",
            "api_key": "   ",
            "base_url": "   ",
            "model_name": "   ",
        }

        with (
            patch.object(model_factory, "settings", _model_settings()),
            patch.object(
                model_factory,
                "_get_runtime_provider_setting",
                return_value=runtime,
            ),
            patch("langchain_openai.ChatOpenAI") as factory,
        ):
            model_factory.get_chat_model()

        self.assertEqual(factory.call_args.kwargs["api_key"], "static-openai-key")
        self.assertEqual(
            factory.call_args.kwargs["base_url"],
            "https://static-openai.test/v1",
        )
        self.assertEqual(factory.call_args.kwargs["model"], "static-chat-model")
        self.assertEqual(factory.call_args.kwargs["temperature"], 0.25)

    def test_anthropic_extended_thinking_forces_temperature_and_exact_kwargs(self) -> None:
        runtime = {
            "provider": "anthropic",
            "api_key": "runtime-anthropic-key",
            "base_url": "https://runtime-anthropic.test",
            "model_name": "claude-runtime",
        }
        settings = _model_settings(anthropic_thinking_budget=4096)

        with (
            patch.object(model_factory, "settings", settings),
            patch.object(
                model_factory,
                "_get_runtime_provider_setting",
                return_value=runtime,
            ),
            patch("langchain_anthropic.ChatAnthropic") as factory,
        ):
            model_factory.get_chat_model(temperature=0.3)

        factory.assert_called_once_with(
            api_key="runtime-anthropic-key",
            model="claude-runtime",
            temperature=1,
            max_tokens=2048,
            streaming=True,
            base_url="https://runtime-anthropic.test",
            thinking={"type": "enabled", "budget_tokens": 4096},
        )

    def test_runtime_lookup_failure_uses_static_provider_configuration(self) -> None:
        settings = _model_settings(llm_provider="openai")

        with (
            patch.object(model_factory, "settings", settings),
            patch.object(
                model_factory,
                "_get_runtime_provider_setting_reader",
                side_effect=RuntimeError("database unavailable"),
            ),
            patch("langchain_openai.ChatOpenAI") as factory,
        ):
            model_factory.get_chat_model()

        self.assertEqual(factory.call_args.kwargs["api_key"], "static-openai-key")
        self.assertEqual(factory.call_args.kwargs["model"], "static-chat-model")

    def test_unknown_provider_preserves_ollama_fallback_contract(self) -> None:
        runtime = {
            "provider": "future-provider",
            "base_url": "https://ignored.test",
            "model_name": "ignored-model",
        }
        model = MagicMock()

        with (
            patch.object(model_factory, "settings", _model_settings()),
            patch.object(
                model_factory,
                "_get_runtime_provider_setting",
                return_value=runtime,
            ),
            patch.object(model_factory, "ChatOllama", return_value=model) as factory,
        ):
            result = model_factory.get_chat_model()

        self.assertIs(result, model)
        factory.assert_called_once_with(
            base_url="http://ollama.test:11434",
            model="static-chat-model",
            temperature=0.25,
        )

    def test_openai_embedding_uses_runtime_fallback_without_siliconflow_flags(self) -> None:
        runtime = {
            "provider": "openai",
            "api_key": "runtime-embedding-key",
            "base_url": "https://runtime-openai.test/v1",
            "model_name": "ignored-runtime-model",
        }

        with (
            patch.object(model_factory, "settings", _model_settings()),
            patch.object(
                model_factory,
                "_get_runtime_provider_setting",
                return_value=runtime,
            ) as runtime_reader,
            patch("langchain_openai.OpenAIEmbeddings") as factory,
        ):
            model_factory.get_embedding_model()

        runtime_reader.assert_called_once_with("openai")
        factory.assert_called_once_with(
            api_key="runtime-embedding-key",
            base_url="https://runtime-openai.test/v1",
            model="static-embedding-model",
            http_client=None,
            tiktoken_enabled=True,
            check_embedding_ctx_length=True,
        )


class RuntimeProviderRouteContracts(unittest.TestCase):
    @staticmethod
    def _client(repository: RuntimeProviderSettingManager) -> TestClient:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.dependency_overrides[
            get_runtime_provider_setting_repository
        ] = lambda: repository
        return TestClient(app)

    def test_empty_config_has_exact_safe_default_projection(self) -> None:
        repository = MagicMock(spec=RuntimeProviderSettingManager)
        repository.get_runtime_provider_setting.return_value = None

        response = self._client(repository).get("/api/ops/provider-config")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "provider": "openai",
                "base_url": "",
                "model_name": "",
                "api_key_configured": False,
                "api_key_masked": None,
                "updated_at": None,
                "reasoning_effort": "",
            },
        )

    def test_key_mask_boundaries_and_timestamp_projection_never_expose_secret(self) -> None:
        cases = (
            ("12345678", "****"),
            ("123456789", "1234****6789"),
        )
        for secret, masked in cases:
            with self.subTest(secret_length=len(secret)):
                repository = MagicMock(spec=RuntimeProviderSettingManager)
                repository.get_runtime_provider_setting.return_value = {
                    "provider": "anthropic",
                    "base_url": "https://example.test",
                    "api_key": secret,
                    "model_name": "example-model",
                    "updated_at": datetime(2026, 7, 28, 12, 34, 56),
                }

                response = self._client(repository).get(
                    "/api/ops/provider-config"
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["api_key_masked"], masked)
                self.assertEqual(
                    response.json()["updated_at"],
                    "2026-07-28 12:34:56",
                )
                self.assertNotIn(secret, response.text)

    def test_update_forwards_blank_preserve_and_explicit_clear_intent(self) -> None:
        repository = MagicMock(spec=RuntimeProviderSettingManager)
        repository.upsert_runtime_provider_setting.return_value = {
            "provider": "anthropic",
            "base_url": "",
            "api_key": None,
            "model_name": "",
        }
        client = self._client(repository)

        response = client.put(
            "/api/ops/provider-config",
            json={
                "provider": "anthropic",
                "api_key": "",
                "clear_api_key": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        repository.upsert_runtime_provider_setting.assert_called_once_with(
            "anthropic",
            "",
            "",
            True,
            "",
            "",
        )
        self.assertEqual(response.json()["api_key_masked"], None)

    def test_provider_validation_and_admin_check_precede_repository_calls(self) -> None:
        repository = MagicMock(spec=RuntimeProviderSettingManager)
        client = self._client(repository)

        invalid = client.put(
            "/api/ops/provider-config",
            json={"provider": "ollama"},
        )

        self.assertEqual(invalid.status_code, 422)
        repository.upsert_runtime_provider_setting.assert_not_called()

        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        app.dependency_overrides[
            get_runtime_provider_setting_repository
        ] = lambda: repository
        unauthorized = TestClient(app).put(
            "/api/ops/provider-config",
            json={"provider": "openai"},
        )

        self.assertIn(unauthorized.status_code, (401, 403))
        repository.upsert_runtime_provider_setting.assert_not_called()


if __name__ == "__main__":
    unittest.main()
