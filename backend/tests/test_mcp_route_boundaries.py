from __future__ import annotations

import ast
import unittest
from pathlib import Path


class McpRouteBoundaryTests(unittest.TestCase):
    def test_route_is_only_an_http_composition_adapter(self) -> None:
        route_path = Path(__file__).parents[1] / "app" / "api" / "routes_mcp.py"
        module = ast.parse(route_path.read_text(encoding="utf-8"), filename=str(route_path))

        functions = {
            node.name
            for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assignments = {
            target.id
            for node in module.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            for target in (
                node.targets if isinstance(node, ast.Assign) else [node.target]
            )
            if isinstance(target, ast.Name)
        }
        imported_names = {
            alias.name
            for node in module.body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        state_accesses = {
            node.attr
            for node in ast.walk(module)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id == "request"
            and node.value.attr == "state"
        }

        self.assertEqual(functions, {"_http_response", "mcp_endpoint"})
        self.assertEqual(assignments, {"router", "_MCP_SESSION_TRANSPORT"})
        self.assertFalse(state_accesses)
        self.assertFalse(
            {
                "MCP_TOOL_REGISTRY",
                "_TOOL_HANDLERS",
                "MCP_TOOLS",
                "MCP_RESOURCES",
                "MCP_RESOURCE_TEMPLATES",
                "MCP_PROMPTS",
                "_call_tool",
                "_read_resource",
                "_get_prompt",
                "_tool_response",
                "_resource_content",
            }
            & imported_names
        )

        endpoint = next(
            node
            for node in module.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "mcp_endpoint"
        )
        called_names = {
            node.func.id
            for node in ast.walk(endpoint)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        called_attributes = {
            node.func.attr
            for node in ast.walk(endpoint)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("parse_mcp_request", called_names)
        self.assertIn("McpProtocolApplication", called_names)
        self.assertEqual(called_attributes, {"post", "error", "dispatch"})


if __name__ == "__main__":
    unittest.main()
