"""源装配契约测试：开关门控、候选解析、缓存与异常路径。

X transport 随公共仓发布。本文件验证其装配路径保持 fail-closed、
可缓存且只暴露公共契约。
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from backend.app.core.config import Settings, settings
from backend.app.services.source_plugins import loader

_LOADER_LOG = "backend.app.services.source_plugins.loader"


def _install_fake_module(test: unittest.TestCase, module: types.ModuleType) -> None:
    """把伪造模块（含缺失父包）注册进 sys.modules，import_module 优先命中。"""
    parts = module.__name__.split(".")
    additions: dict[str, types.ModuleType] = {}
    for index in range(1, len(parts)):
        package = ".".join(parts[:index])
        if package not in sys.modules:
            additions[package] = types.ModuleType(package)
    additions[module.__name__] = module
    patcher = mock.patch.dict(sys.modules, additions)
    patcher.start()
    test.addCleanup(patcher.stop)


class _SourcePluginTestCase(unittest.TestCase):
    def setUp(self) -> None:
        loader._reset_plugin_cache()
        self.addCleanup(loader._reset_plugin_cache)


class SourceFlagDefaultsTests(unittest.TestCase):
    def test_source_flags_default_off(self) -> None:
        self.assertIs(Settings.model_fields["x_source_enabled"].default, False)

    def test_wechat_source_flag_removed(self) -> None:
        self.assertNotIn("wechat_source_enabled", Settings.model_fields)


class XSourceSwitchTests(_SourcePluginTestCase):
    def test_flag_off_returns_none(self) -> None:
        with mock.patch.object(settings, "x_source_enabled", False):
            self.assertIsNone(loader.load_x_transport_class())

    def test_flag_on_loads_public_candidate(self) -> None:
        fake = types.ModuleType("backend.app.services.ingestion.sources.x_transport")
        sentinel = type("XTransport", (), {})
        fake.XTransport = sentinel  # type: ignore[attr-defined]
        _install_fake_module(self, fake)
        with mock.patch.object(settings, "x_source_enabled", True):
            self.assertIs(loader.load_x_transport_class(), sentinel)

    def test_plugin_missing_returns_none_with_warning(self) -> None:
        with (
            mock.patch.object(settings, "x_source_enabled", True),
            mock.patch.object(loader, "_X_TRANSPORT_MODULES", ("nonexistent_source_plugin.x",)),
            self.assertLogs(_LOADER_LOG, level="WARNING") as captured,
        ):
            self.assertIsNone(loader.load_x_transport_class())
        self.assertTrue(any("均不可导入" in message for message in captured.output))

    def test_module_without_xtransport_returns_none_with_warning(self) -> None:
        fake = types.ModuleType("backend.app.services.ingestion.sources.x_transport")
        _install_fake_module(self, fake)
        with (
            mock.patch.object(settings, "x_source_enabled", True),
            self.assertLogs(_LOADER_LOG, level="WARNING") as captured,
        ):
            self.assertIsNone(loader.load_x_transport_class())
        self.assertTrue(any("缺少 XTransport" in message for message in captured.output))

    def test_load_result_cached(self) -> None:
        fake = types.ModuleType("backend.app.services.ingestion.sources.x_transport")
        fake.XTransport = type("XTransport", (), {})  # type: ignore[attr-defined]
        _install_fake_module(self, fake)
        with (
            mock.patch.object(settings, "x_source_enabled", True),
            mock.patch.object(
                loader.importlib,
                "import_module",
                wraps=loader.importlib.import_module,
            ) as spy,
        ):
            first = loader.load_x_transport_class()
            second = loader.load_x_transport_class()
        self.assertIsNotNone(first)
        self.assertIs(first, second)
        self.assertEqual(spy.call_count, 1)


if __name__ == "__main__":
    unittest.main()
