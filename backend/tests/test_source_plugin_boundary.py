"""可插拔源边界守护（3F）：公共仓只保留接口，实现不得回流。

锁定三条不变量（OSS-only 环境全套通过的前提）：

1. 公共 Python 代码（backend/app、backend/tests、scripts）不得以 import
   语句引入 ``aigcnews_private`` 或 ``twitter_cli``——插件解析只许经
   loader 的字符串候选间接发生；
2. loader 候选只含私有模块路径（无仓库内回退候选）；
3. 过渡期仓库内实现模块保持删除，requirements 不含 twitter-cli。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from backend.app.services.source_plugins import loader

REPO_ROOT = Path(__file__).resolve().parents[2]

FORBIDDEN_IMPORT_ROOTS = ("aigcnews_private", "twitter_cli")

SCAN_DIRS = (
    REPO_ROOT / "backend" / "app",
    REPO_ROOT / "backend" / "tests",
    REPO_ROOT / "scripts",
)

DELETED_PATHS = (
    REPO_ROOT / "backend" / "app" / "services" / "wechat",
    REPO_ROOT / "backend" / "app" / "services" / "wechat_sogou",
    REPO_ROOT / "backend" / "app" / "services" / "ingestion" / "sources" / "x_transport.py",
    REPO_ROOT / "backend" / "app" / "services" / "source_plugins" / "_wechat_inrepo_facade.py",
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
    def test_no_public_module_imports_private_package_or_twitter_cli(self) -> None:
        offenders: list[str] = []
        for scan_dir in SCAN_DIRS:
            for path in sorted(scan_dir.rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                hits = _imported_roots(path) & set(FORBIDDEN_IMPORT_ROOTS)
                if hits:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {sorted(hits)}")
        self.assertEqual(offenders, [])


class SourcePluginLoaderShapeTests(unittest.TestCase):
    def test_loader_candidates_are_private_only(self) -> None:
        for candidates in (loader._X_TRANSPORT_MODULES, loader._WECHAT_FACADE_MODULES):
            self.assertTrue(candidates)
            for name in candidates:
                self.assertTrue(
                    name.startswith("aigcnews_private."),
                    f"出现仓库内回退候选: {name}",
                )


class SourcePluginDeletionTests(unittest.TestCase):
    def test_inrepo_transition_modules_stay_deleted(self) -> None:
        survivors = [str(p.relative_to(REPO_ROOT)) for p in DELETED_PATHS if p.exists()]
        self.assertEqual(survivors, [])

    def test_requirements_exclude_twitter_cli(self) -> None:
        requirements = (REPO_ROOT / "backend" / "requirements.txt").read_text(
            encoding="utf-8"
        )
        lock = (REPO_ROOT / "backend" / "requirements.lock").read_text(encoding="utf-8")
        self.assertNotIn("twitter-cli", requirements)
        self.assertNotIn("twitter-cli==", lock)


if __name__ == "__main__":
    unittest.main()
