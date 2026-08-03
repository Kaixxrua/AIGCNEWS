from __future__ import annotations

import ast
from pathlib import Path

_SERVICES_ROOT = Path("backend/app/services")


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_services_layer_does_not_import_api_layer() -> None:
    """服务层禁止依赖传输层（api/*）：契约/schema 归属 services/mcp/contracts.py。"""
    offenders: list[str] = []
    for path in sorted(_SERVICES_ROOT.rglob("*.py")):
        imported = _imported_modules(path)
        if any(
            module == "backend.app.api" or module.startswith("backend.app.api.")
            for module in imported
        ):
            offenders.append(str(path))
    assert offenders == [], f"services → api 反向依赖: {offenders}"
