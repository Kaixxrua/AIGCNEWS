"""可插拔源边界守护：X 实现公开，微信公众号功能已从公共仓整体移除。

锁定以下不变量：

1. 公共 Python 代码不得直接导入 ``aigcnews_private``；
2. ``twitter_cli`` 只能由公共 X transport、兼容层及其专项测试直接导入；
3. X loader 只有仓库内 canonical transport 候选，loader 不再装配任何微信门面；
4. 微信实现、路由、仓储与插件契约保持删除，且 ``twitter-cli==0.8.5`` 在直接依赖与
   lock 中精确锁定。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from backend.app.services.source_plugins import loader

REPO_ROOT = Path(__file__).resolve().parents[2]

SCAN_DIRS = (
    REPO_ROOT / "backend" / "app",
    REPO_ROOT / "backend" / "tests",
    REPO_ROOT / "scripts",
)

TWITTER_CLI_IMPORT_ALLOWLIST = frozenset(
    {
        Path("backend/app/services/ingestion/sources/x_transport.py"),
        Path("backend/app/services/ingestion/sources/x_twitter_cli_compat.py"),
        Path("backend/tests/test_x_source_contracts.py"),
        Path("backend/tests/test_x_twitter_cli_compat.py"),
    }
)

DELETED_PRIVATE_SOURCE_PATHS = (
    REPO_ROOT / "backend" / "app" / "services" / "wechat",
    REPO_ROOT / "backend" / "app" / "services" / "wechat_sogou",
    REPO_ROOT
    / "backend"
    / "app"
    / "services"
    / "source_plugins"
    / "_wechat_inrepo_facade.py",
    REPO_ROOT / "backend" / "app" / "services" / "source_plugins" / "wechat_source.py",
    REPO_ROOT / "backend" / "app" / "api" / "routes_wechat.py",
    REPO_ROOT / "backend" / "app" / "api" / "routes_wechat_media.py",
    REPO_ROOT / "backend" / "app" / "models" / "schema_wechat.py",
)


def _imported_roots(path: Path) -> set[str]:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


class SourcePluginImportBoundaryTests(unittest.TestCase):
    def test_no_public_module_imports_private_package(self) -> None:
        offenders: list[str] = []
        for scan_dir in SCAN_DIRS:
            for path in sorted(scan_dir.rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                if "aigcnews_private" in _imported_roots(path):
                    offenders.append(str(path.relative_to(REPO_ROOT)))
        self.assertEqual(offenders, [])

    def test_twitter_cli_imports_are_narrowly_allowlisted(self) -> None:
        importers: set[Path] = set()
        for scan_dir in SCAN_DIRS:
            for path in sorted(scan_dir.rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                if "twitter_cli" in _imported_roots(path):
                    importers.add(path.relative_to(REPO_ROOT))
        self.assertEqual(importers, set(TWITTER_CLI_IMPORT_ALLOWLIST))


class SourcePluginLoaderShapeTests(unittest.TestCase):
    def test_x_loader_has_single_public_candidate(self) -> None:
        self.assertEqual(
            loader._X_TRANSPORT_MODULES,
            ("backend.app.services.ingestion.sources.x_transport",),
        )

    def test_loader_no_longer_wires_wechat(self) -> None:
        self.assertFalse(hasattr(loader, "_WECHAT_FACADE_MODULES"))
        self.assertFalse(hasattr(loader, "load_wechat_bundle"))


class SourcePluginRepositoryShapeTests(unittest.TestCase):
    def test_public_x_transport_exists(self) -> None:
        self.assertTrue(
            (
                REPO_ROOT
                / "backend"
                / "app"
                / "services"
                / "ingestion"
                / "sources"
                / "x_transport.py"
            ).is_file()
        )

    def test_wechat_modules_stay_deleted(self) -> None:
        survivors = [
            str(path.relative_to(REPO_ROOT))
            for path in DELETED_PRIVATE_SOURCE_PATHS
            if path.exists()
        ]
        self.assertEqual(survivors, [])

    def test_twitter_cli_is_exactly_pinned(self) -> None:
        requirements = (REPO_ROOT / "backend" / "requirements.txt").read_text(
            encoding="utf-8"
        )
        lock = (REPO_ROOT / "backend" / "requirements.lock").read_text(
            encoding="utf-8"
        )
        requirement_lines = {
            line.strip()
            for line in requirements.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("twitter-cli==0.8.5", requirement_lines)
        self.assertIn("twitter-cli==0.8.5", lock)


if __name__ == "__main__":
    unittest.main()
