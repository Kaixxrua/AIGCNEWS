from __future__ import annotations

import ast
from pathlib import Path


def test_ops_routes_depend_only_on_diagnostics_application_service() -> None:
    route_path = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "api"
        / "routes_ops.py"
    )
    module = ast.parse(route_path.read_text(encoding="utf-8"))
    imported_names = {
        alias.name
        for node in ast.walk(module)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert {
        "OpsDiagnosticsService",
        "get_ops_diagnostics_service",
    } <= imported_names
    assert imported_names.isdisjoint(
        {
            "WEBSITE_TAXONOMY",
            "project_catalog_runtime_readiness",
            "project_search_shadow_snapshot",
            "finalize_project_search_shadow",
            "settings",
        }
    )
