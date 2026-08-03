from __future__ import annotations

import ast
from pathlib import Path

_SERVICES_ROOT = Path("backend/app/services")
_REPOSITORIES_ROOT = Path("backend/app/repositories")


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


def test_services_layer_does_not_import_fastapi_http_exception() -> None:
    """服务层禁止 import fastapi.HTTPException：抛领域异常，HTTP 映射在路由层。"""
    offenders: list[str] = []
    for path in sorted(_SERVICES_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module
                and node.module.startswith("fastapi")
                and any(alias.name == "HTTPException" for alias in node.names)
            ):
                offenders.append(str(path))
    assert offenders == [], f"services 层 import HTTPException: {offenders}"


def test_repositories_layer_does_not_import_services_layer() -> None:
    """仓储层禁止依赖服务层：共享纯函数/词表归属 domain/。

    project_taxonomy 与 search_semantics 已归位 backend/app/domain/。
    """
    offenders: list[str] = []
    for path in sorted(_REPOSITORIES_ROOT.rglob("*.py")):
        imported = {
            module
            for module in _imported_modules(path)
            if module == "backend.app.services"
            or module.startswith("backend.app.services.")
        }
        if imported:
            offenders.append(f"{path} -> {sorted(imported)}")
    assert offenders == [], f"repositories → services 反向依赖: {offenders}"
