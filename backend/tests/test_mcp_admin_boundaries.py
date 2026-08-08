from __future__ import annotations

import ast
import unittest
from pathlib import Path


class McpAdminBoundaryTests(unittest.TestCase):
    def test_ops_routes_and_tester_delegate_to_extracted_boundaries(self) -> None:
        app_directory = Path(__file__).parents[1] / "app"
        expectations = {
            app_directory / "api" / "routes_ops_mcp.py": {
                "required": {"McpAdminService", "get_mcp_admin_service"},
                "forbidden_imports": {
                    "McpServerConfigRepository",
                    "project_server",
                    "test_mcp_server_connection",
                    "validate_mcp_http_url",
                },
                "forbidden_functions": {"_mcp_payload", "_parse_mcp_tools"},
            },
            app_directory / "services" / "mcp_connection_tester.py": {
                "required": {
                    "StreamableHttpTransport",
                    "initialize_payload",
                    "initialized_payload",
                    "tools_list_payload",
                    "validate_json_rpc_data",
                },
                "forbidden_functions": {
                    "_mcp_payload",
                    "_extract_tools",
                    "_extract_protocol_version",
                    "_parse_sse_event",
                    "_json_from_sse",
                },
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

    def test_connection_tester_compatibility_exports_remain_available(self) -> None:
        from backend.app.services import mcp_connection_tester

        self.assertTrue(issubclass(mcp_connection_tester.McpConnectionTestError, ValueError))
        self.assertTrue(callable(mcp_connection_tester.validate_mcp_http_url))
        self.assertTrue(callable(mcp_connection_tester.test_mcp_server_connection))


if __name__ == "__main__":
    unittest.main()
