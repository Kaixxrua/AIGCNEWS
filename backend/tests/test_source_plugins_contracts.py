"""源插件契约测试：开关门控、候选回退优先级、缓存与公共契约面一致性。"""

from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from backend.app.core.config import Settings, settings
from backend.app.services.source_plugins import loader
from backend.app.services.source_plugins.wechat_source import (
    WeChatAccountServiceProtocol,
    WeChatError,
    WeChatFollowServiceProtocol,
    WeChatLoginServiceProtocol,
    WeChatServiceBundle,
    WeChatSyncServiceProtocol,
)
from backend.app.services.source_plugins.x_source import (
    XAuthAbort,
    XAuthNotConfigured,
    XRateLimitAbort,
    XTransportProtocol,
    XTransportUnavailable,
)

_LOADER_LOG = "backend.app.services.source_plugins.loader"
_INREPO_X_TRANSPORT = "backend.app.services.ingestion.sources.x_transport"
_INREPO_WECHAT_FACADE = "backend.app.services.source_plugins._wechat_inrepo_facade"


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

    def test_flag_on_loads_inrepo_impl(self) -> None:
        from backend.app.services.ingestion.sources import x_transport

        with (
            mock.patch.object(settings, "x_source_enabled", True),
            mock.patch.object(loader, "_X_TRANSPORT_MODULES", (_INREPO_X_TRANSPORT,)),
        ):
            self.assertIs(loader.load_x_transport_class(), x_transport.XTransport)

    def test_private_candidate_takes_priority(self) -> None:
        fake = types.ModuleType("aigcnews_private.sources.x_transport")
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
        fake = types.ModuleType("aigcnews_private.sources.x_transport")
        _install_fake_module(self, fake)
        with (
            mock.patch.object(settings, "x_source_enabled", True),
            mock.patch.object(loader, "_X_TRANSPORT_MODULES", (fake.__name__,)),
            self.assertLogs(_LOADER_LOG, level="WARNING") as captured,
        ):
            self.assertIsNone(loader.load_x_transport_class())
        self.assertTrue(any("缺少 XTransport" in message for message in captured.output))

    def test_load_result_cached(self) -> None:
        with (
            mock.patch.object(settings, "x_source_enabled", True),
            mock.patch.object(loader, "_X_TRANSPORT_MODULES", (_INREPO_X_TRANSPORT,)),
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


class XContractIdentityTests(unittest.TestCase):
    """过渡期仓库内实现与公共契约共享同一组异常/常量，调用方无感知。"""

    def test_exceptions_and_constant_shared_with_impl(self) -> None:
        from backend.app.services.ingestion.sources import x_transport
        from backend.app.services.source_plugins import x_source

        self.assertIs(x_transport.XAuthAbort, XAuthAbort)
        self.assertIs(x_transport.XAuthNotConfigured, XAuthNotConfigured)
        self.assertIs(x_transport.XRateLimitAbort, XRateLimitAbort)
        self.assertIs(x_transport.XTransportUnavailable, XTransportUnavailable)
        self.assertEqual(
            x_transport.DEFAULT_INTER_ACCOUNT_DELAY,
            x_source.DEFAULT_INTER_ACCOUNT_DELAY,
        )

    def test_impl_satisfies_transport_protocol(self) -> None:
        from backend.app.services.ingestion.sources import x_transport

        self.assertTrue(issubclass(x_transport.XTransport, XTransportProtocol))


class WeChatSourceSwitchTests(_SourcePluginTestCase):
    def test_flag_off_returns_none(self) -> None:
        with mock.patch.object(settings, "wechat_source_enabled", False):
            self.assertIsNone(loader.load_wechat_bundle())

    def test_flag_on_loads_inrepo_bundle(self) -> None:
        from backend.app.services.wechat import (
            account_service,
            errors,
            follow_service,
            login_service,
            sync_service,
            transport,
        )
        from backend.app.services.wechat_sogou import transport as sogou_transport

        with (
            mock.patch.object(settings, "wechat_source_enabled", True),
            mock.patch.object(loader, "_WECHAT_FACADE_MODULES", (_INREPO_WECHAT_FACADE,)),
        ):
            bundle = loader.load_wechat_bundle()
        self.assertIsInstance(bundle, WeChatServiceBundle)
        assert bundle is not None
        self.assertIs(bundle.mp_transport, transport.WeChatMpTransport)
        self.assertIs(bundle.sogou_transport, sogou_transport.SogouWechatTransport)
        self.assertIs(bundle.login_service, login_service.WeChatLoginService)
        self.assertIs(bundle.account_service, account_service.WeChatAccountService)
        self.assertIs(bundle.follow_service, follow_service.WeChatFollowService)
        self.assertIs(bundle.sync_service, sync_service.WeChatSyncService)
        self.assertIs(bundle.error, errors.WeChatError)

    def test_private_candidate_takes_priority(self) -> None:
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


class WeChatContractIdentityTests(unittest.TestCase):
    """过渡期仓库内实现与公共契约共享错误基类，并满足服务方法面 Protocol。"""

    def test_error_base_shared_with_impl(self) -> None:
        from backend.app.services.wechat import errors

        self.assertIs(errors.WeChatError, WeChatError)
        self.assertTrue(issubclass(errors.WeChatSessionExpired, WeChatError))
        self.assertTrue(issubclass(errors.WeChatUpstreamError, WeChatError))

    def test_impl_services_satisfy_protocols(self) -> None:
        from backend.app.services.wechat import (
            account_service,
            follow_service,
            login_service,
            sync_service,
        )

        self.assertTrue(
            issubclass(login_service.WeChatLoginService, WeChatLoginServiceProtocol)
        )
        self.assertTrue(
            issubclass(account_service.WeChatAccountService, WeChatAccountServiceProtocol)
        )
        self.assertTrue(
            issubclass(sync_service.WeChatSyncService, WeChatSyncServiceProtocol)
        )
        self.assertTrue(
            issubclass(follow_service.WeChatFollowService, WeChatFollowServiceProtocol)
        )
