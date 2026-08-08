from __future__ import annotations

import inspect
import unittest
from typing import Any

from backend.app.repositories.runtime_provider_repository import (
    RuntimeProviderSettingManager,
    RuntimeProviderSettingReader,
    RuntimeProviderSettingRepository,
)


def _without_annotations(function: Any) -> inspect.Signature:
    signature = inspect.signature(function)
    return signature.replace(
        parameters=[
            parameter.replace(annotation=inspect.Parameter.empty)
            for parameter in signature.parameters.values()
        ],
        return_annotation=inspect.Signature.empty,
    )


class RuntimeProviderRepositoryContractTests(unittest.TestCase):
    def test_reader_exposes_only_internal_lookup(self) -> None:
        public_methods = {
            name
            for name, value in RuntimeProviderSettingReader.__dict__.items()
            if not name.startswith("_") and callable(value)
        }
        self.assertEqual(public_methods, {"get_runtime_provider_setting"})
        self.assertNotIn(
            "upsert_runtime_provider_setting",
            RuntimeProviderSettingReader.__dict__,
        )

    def test_manager_and_combined_repository_preserve_capabilities(self) -> None:
        self.assertIn(
            RuntimeProviderSettingReader,
            RuntimeProviderSettingManager.__mro__,
        )
        self.assertIn(
            RuntimeProviderSettingManager,
            RuntimeProviderSettingRepository.__mro__,
        )

    def test_runtime_setting_signatures_are_frozen(self) -> None:
        self.assertEqual(
            str(
                _without_annotations(
                    RuntimeProviderSettingReader.get_runtime_provider_setting
                )
            ),
            "(self, provider='')",
        )
        self.assertEqual(
            str(
                _without_annotations(
                    RuntimeProviderSettingManager.upsert_runtime_provider_setting
                )
            ),
            "(self, provider, base_url='', api_key=None, clear_api_key=False, model_name='', reasoning_effort='')",
        )
        self.assertEqual(
            str(
                _without_annotations(
                    RuntimeProviderSettingManager.update_enrichment_reasoning_effort
                )
            ),
            "(self, reasoning_effort='')",
        )


if __name__ == "__main__":
    unittest.main()
