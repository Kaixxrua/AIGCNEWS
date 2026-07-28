from __future__ import annotations

import ast
import unittest
from pathlib import Path


class AuthRouteBoundaryTests(unittest.TestCase):
    def test_account_routes_delegate_without_persistence_construction(self) -> None:
        route_path = (
            Path(__file__).parents[1] / "app" / "api" / "routes_auth.py"
        )
        module = ast.parse(route_path.read_text(encoding="utf-8"))

        imports = {
            alias.name
            for node in ast.walk(module)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        self.assertNotIn("MySQLRepository", imports)
        self.assertIn("build_account_lifecycle", imports)

        account_routes = {
            node.name: node
            for node in module.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name
            in {
                "send_password_reset_otp",
                "reset_password",
                "register",
                "login",
            }
        }
        self.assertEqual(
            set(account_routes),
            {
                "send_password_reset_otp",
                "reset_password",
                "register",
                "login",
            },
        )
        for name, function in account_routes.items():
            calls = {
                node.func.id
                for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
            }
            self.assertIn("build_account_lifecycle", calls, name)
            self.assertNotIn("MySQLRepository", calls, name)


if __name__ == "__main__":
    unittest.main()
