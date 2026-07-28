from __future__ import annotations

import unittest
from datetime import datetime

from backend.app.services.runtime_provider.control_plane import (
    RuntimeProviderConfig,
    RuntimeProviderUpdate,
    effective_model_name,
    effective_value,
    mask_api_key,
    normalize_provider,
    project_provider_config,
    resolve_chat_config,
)


class RuntimeProviderControlPlaneTests(unittest.TestCase):
    def test_runtime_config_normalizes_provider_and_secret_values(self) -> None:
        config = RuntimeProviderConfig.from_row(
            {
                "provider": " Anthropic ",
                "base_url": " https://example.test ",
                "model_name": " claude-example ",
                "api_key": " secret-value ",
            }
        )

        self.assertEqual(config.provider, "anthropic")
        self.assertEqual(config.base_url, "https://example.test")
        self.assertEqual(config.model_name, "claude-example")
        self.assertEqual(config.api_key, "secret-value")

    def test_update_intent_keeps_clear_separate_from_replacement(self) -> None:
        update = RuntimeProviderUpdate.from_values(
            provider=" OpenAI ",
            base_url=" https://example.test/v1 ",
            api_key=" replacement-secret ",
            clear_api_key=True,
            model_name=" example-model ",
        )

        self.assertEqual(update.provider, "openai")
        self.assertEqual(update.api_key, "replacement-secret")
        self.assertTrue(update.clear_api_key)

    def test_effective_values_ignore_blank_runtime_fields(self) -> None:
        row = {"api_key": "   ", "model_name": ""}

        self.assertEqual(effective_value(row, "api_key", "fallback"), "fallback")
        self.assertEqual(effective_model_name(row, "fallback-model"), "fallback-model")

    def test_chat_resolution_preserves_runtime_precedence_and_zero_temperature(self) -> None:
        resolved = resolve_chat_config(
            {
                "provider": " OpenAI ",
                "api_key": " runtime-key ",
                "base_url": " https://runtime.test/v1 ",
                "model_name": " runtime-model ",
            },
            fallback_provider="ollama",
            fallback_api_key="static-key",
            fallback_base_url="https://static.test/v1",
            fallback_model_name="static-model",
            fallback_temperature=0.7,
            temperature=0,
        )

        self.assertEqual(resolved.provider, "openai")
        self.assertEqual(resolved.api_key, "runtime-key")
        self.assertEqual(resolved.base_url, "https://runtime.test/v1")
        self.assertEqual(resolved.model_name, "runtime-model")
        self.assertEqual(resolved.temperature, 0)

    def test_safe_projection_contains_only_redacted_secret_metadata(self) -> None:
        secret = "runtime-provider-secret"
        projection = project_provider_config(
            {
                "provider": "openai",
                "base_url": "https://example.test/v1",
                "model_name": "example-model",
                "api_key": secret,
                "updated_at": datetime(2026, 7, 28, 12, 34, 56),
            }
        )

        self.assertTrue(projection.api_key_configured)
        self.assertEqual(projection.api_key_masked, "runt****cret")
        self.assertEqual(projection.updated_at, "2026-07-28 12:34:56")
        self.assertNotIn(secret, repr(projection))
        self.assertFalse(hasattr(projection, "api_key"))

    def test_key_mask_and_provider_fallback_match_existing_contract(self) -> None:
        self.assertIsNone(mask_api_key(None))
        self.assertEqual(mask_api_key("12345678"), "****")
        self.assertEqual(mask_api_key("123456789"), "1234****6789")
        self.assertEqual(normalize_provider(""), "ollama")
        self.assertEqual(normalize_provider(None, fallback="openai"), "openai")


if __name__ == "__main__":
    unittest.main()
