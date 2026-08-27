"""源装配契约测试：开关门控、候选解析、缓存与异常路径。

X transport 随公共仓发布；微信公众号实现仍由私有包
``aigcnews_private`` 提供。本文件验证两种装配路径都保持 fail-closed、
可缓存且只暴露公共契约。
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from backend.app.core.config import Settings, settings
from backend.app.services.source_plugins import loader
from backend.app.services.source_plugins.wechat_source import WeChatError

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
        self.assertIs(Settings.model_fields["wechat_source_enabled"].default, False)


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


class WeChatSourceSwitchTests(_SourcePluginTestCase):
    def test_flag_off_returns_none(self) -> None:
        with mock.patch.object(settings, "wechat_source_enabled", False):
            self.assertIsNone(loader.load_wechat_bundle())

    def test_flag_on_loads_private_candidate(self) -> None:
        fake = types.ModuleType("aigcnews_private.sources.wechat_facade")
        for attr in loader._WECHAT_BUNDLE_ATTRS.values():
            setattr(fake, attr, type(attr, (), {}))
        _install_fake_module(self, fake)
        with mock.patch.object(settings, "wechat_source_enabled", True):
            bundle = loader.load_wechat_bundle()
        self.assertIsNotNone(bundle)
        assert bundle is not None
        self.assertIs(bundle.mp_transport, getattr(fake, "WeChatMpTransport"))
        self.assertIs(bundle.error, getattr(fake, "WeChatError"))

    def test_plugin_missing_returns_none_with_warning(self) -> None:
        with (
            mock.patch.object(settings, "wechat_source_enabled", True),
            mock.patch.object(
                loader,
                "_WECHAT_FACADE_MODULES",
                ("nonexistent_source_plugin.wechat_facade",),
            ),
            self.assertLogs(_LOADER_LOG, level="WARNING") as captured,
        ):
            self.assertIsNone(loader.load_wechat_bundle())
        self.assertTrue(any("均不可导入" in message for message in captured.output))

    def test_facade_missing_attrs_returns_none_with_warning(self) -> None:
        fake = types.ModuleType("aigcnews_private.sources.wechat_facade")
        fake.WeChatError = WeChatError  # type: ignore[attr-defined]
        _install_fake_module(self, fake)
        with (
            mock.patch.object(settings, "wechat_source_enabled", True),
            self.assertLogs(_LOADER_LOG, level="WARNING") as captured,
        ):
            self.assertIsNone(loader.load_wechat_bundle())
        self.assertTrue(any("缺少属性" in message for message in captured.output))


if __name__ == "__main__":
    unittest.main()
