from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.services.runtime_provider.adapters import (
    ProviderConstructors,
    RuntimeSettingSource,
)


class RuntimeProviderAdapterTests(unittest.TestCase):
    def test_runtime_source_returns_row_from_narrow_reader(self) -> None:
        reader = MagicMock()
        reader.get_runtime_provider_setting.return_value = {
            "provider": "openai",
            "api_key": "internal-secret",
        }
        source = RuntimeSettingSource(lambda: reader)

        result = source.read("openai")

        self.assertEqual(result["provider"], "openai")
        reader.get_runtime_provider_setting.assert_called_once_with("openai")

    def test_runtime_source_silently_falls_back_on_storage_failure(self) -> None:
        source = RuntimeSettingSource(
            lambda: (_ for _ in ()).throw(RuntimeError("database unavailable"))
        )

        self.assertEqual(source.read(), {})

    def test_provider_constructors_are_lazy_and_forward_exact_kwargs(self) -> None:
        openai_type = MagicMock()
        openai_factory = MagicMock(return_value=openai_type)
        constructors = ProviderConstructors(
            openai_chat=openai_factory,
            anthropic_chat=MagicMock(),
            ollama_chat=MagicMock(),
            openai_embeddings=MagicMock(),
            huggingface_embeddings=MagicMock(),
            ollama_embeddings=MagicMock(),
        )
        kwargs = {
            "api_key": "internal-secret",
            "model": "example-model",
            "temperature": 0,
        }

        constructors.create_openai_chat(kwargs)

        openai_factory.assert_called_once_with()
        openai_type.assert_called_once_with(**kwargs)


if __name__ == "__main__":
    unittest.main()
