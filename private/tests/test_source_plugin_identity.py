"""私有实现与公共契约的一致性：身份共享、Protocol 满足、loader 默认候选直取。

公共仓 test_source_plugins_contracts.py 覆盖开关门控/异常路径（fake 模块）；
本文件覆盖只有私有包在场才能断言的部分——实现类与契约对象的身份同一性、
loader 默认候选（私有唯一）加载出真实实现。

运行前提：PYTHONPATH 同时覆盖公共仓与本仓（本仓 conftest.py 已自动注入）。
"""

from __future__ import annotations

import importlib.util
import unittest
from unittest import mock

from aigcnews_private.sources import x_transport
from backend.app.core.config import settings
from backend.app.services.source_plugins import loader
from backend.app.services.source_plugins.x_source import (
    XAuthAbort,
    XAuthNotConfigured,
    XRateLimitAbort,
    XTransportProtocol,
    XTransportUnavailable,
)


class _SourcePluginTestCase(unittest.TestCase):
    def setUp(self) -> None:
        loader._reset_plugin_cache()
        self.addCleanup(loader._reset_plugin_cache)


class XContractIdentityTests(unittest.TestCase):
    """私有实现与公共契约共享同一组异常/常量，调用方无感知。"""

    def test_exceptions_and_constant_shared_with_contract(self) -> None:
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
        self.assertTrue(issubclass(x_transport.XTransport, XTransportProtocol))


class XSourceDefaultCandidateTests(_SourcePluginTestCase):
    def test_flag_on_loads_private_impl_via_default_candidates(self) -> None:
        with mock.patch.object(settings, "x_source_enabled", True):
            self.assertIs(loader.load_x_transport_class(), x_transport.XTransport)


class WeChatRetiredTests(unittest.TestCase):
    """微信公众号链路 2026-09-29 已整体下线，私有实现不得复活。"""

    def test_wechat_implementation_stays_deleted(self) -> None:
        for module in (
            "aigcnews_private.sources.wechat",
            "aigcnews_private.sources.wechat_sogou",
            "aigcnews_private.sources.wechat_facade",
        ):
            self.assertIsNone(importlib.util.find_spec(module), module)


if __name__ == "__main__":
    unittest.main()
