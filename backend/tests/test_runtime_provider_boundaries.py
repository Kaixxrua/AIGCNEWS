from __future__ import annotations

import ast
import unittest
from pathlib import Path


class RuntimeProviderBoundaryTests(unittest.TestCase):
    def test_ops_route_and_model_factory_delegate_to_control_plane(self) -> None:
        app_directory = Path(__file__).parents[1] / "app"
        expectations = {
            app_directory / "api" / "routes_ops.py": {
                "required": {
                    "RuntimeProviderAdminService",
                    "get_runtime_provider_admin_service",
                },
                "forbidden_imports": {
                    "RuntimeProviderSettingManager",
                    "RuntimeProviderUpdate",
                    "project_provider_config",
                },
                "forbidden_functions": {"_mask_api_key", "_provider_config_response"},
            },
            app_directory / "core" / "model_factory.py": {
                "required": {
                    "ProviderConstructors",
                    "RuntimeSettingSource",
                    "effective_value",
                    "resolve_chat_config",
                },
                "forbidden_functions": {"_runtime_value", "_runtime_model_name"},
            },
        }

        for path, expectation in expectations.items():
            with self.subTest(path=path.name):
                module = ast.parse(path.read_text(encoding="utf-8"))
                imported = {
                    alias.asname or alias.name
                    for node in ast.walk(module)
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names
                }
                functions = {
                    node.name
                    for node in ast.walk(module)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                self.assertTrue(expectation["required"] <= imported)
                self.assertFalse(expectation.get("forbidden_imports", set()) & imported)
                self.assertFalse(expectation["forbidden_functions"] & functions)

    def test_public_model_factory_signatures_remain_available(self) -> None:
        from backend.app.core import model_factory

        self.assertTrue(callable(model_factory.get_chat_model))
        self.assertTrue(callable(model_factory.get_embedding_model))


if __name__ == "__main__":
    unittest.main()
