from __future__ import annotations

import ast
import unittest
from pathlib import Path


class SchedulerRuntimeBoundaryTests(unittest.TestCase):
    def test_application_owns_scheduler_runtime_without_global_lifecycle_calls(self) -> None:
        app_directory = Path(__file__).parents[1] / "app"
        retired_names = {
            "get_scheduler",
            "start_scheduler",
            "stop_scheduler",
            "lifespan_scheduler",
        }

        for path in app_directory.rglob("*.py"):
            with self.subTest(path=path.relative_to(app_directory)):
                module = ast.parse(path.read_text(encoding="utf-8"))
                imported = {
                    alias.asname or alias.name
                    for node in ast.walk(module)
                    if isinstance(node, (ast.Import, ast.ImportFrom))
                    for alias in node.names
                }
                called = {
                    node.func.id
                    for node in ast.walk(module)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                }
                self.assertFalse(retired_names & imported)
                self.assertFalse(retired_names & called)

    def test_application_runtime_state_is_composed_only_by_lifespan(self) -> None:
        app_directory = Path(__file__).parents[1] / "app"
        dependencies = (app_directory / "api" / "dependencies.py").read_text(
            encoding="utf-8"
        )

        # 应用状态只允许由 lifespan 组合根赋值。组合根只有主进程 main.py
        # （独立 MCP 进程 mcp_main.py 已随 W6-U3 退役删除）。
        # scheduler_runtime 仍钉死在 main.py。
        composition_roots = app_directory / "main.py"
        allowed_assigners = {
            "scheduler_runtime": {composition_roots},
            "project_search_runtime": {composition_roots},
            "monitoring_runtime": {composition_roots},
        }

        for attribute, allowed in allowed_assigners.items():
            assignments: list[Path] = []
            reads: list[Path] = []
            for path in app_directory.rglob("*.py"):
                module = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(module):
                    if not isinstance(node, ast.Attribute) or node.attr != attribute:
                        continue
                    if isinstance(node.ctx, ast.Store):
                        assignments.append(path)
                    elif isinstance(node.ctx, ast.Load):
                        reads.append(path)

            with self.subTest(attribute=attribute):
                self.assertTrue(assignments)
                self.assertEqual(set(assignments), allowed)
                self.assertEqual(reads, [])
                self.assertIn(
                    f'getattr(request.app.state, "{attribute}", None)',
                    dependencies,
                )


if __name__ == "__main__":
    unittest.main()
