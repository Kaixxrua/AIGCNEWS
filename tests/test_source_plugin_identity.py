"""私有实现与公共契约的一致性：身份共享、Protocol 满足、loader 默认候选直取。

公共仓 test_source_plugins_contracts.py 覆盖开关门控/异常路径（fake 模块）；
本文件覆盖只有私有包在场才能断言的部分——实现类与契约对象的身份同一性、
门面属性面完整性、loader 默认候选（私有唯一）加载出真实实现。

运行前提：PYTHONPATH 同时覆盖公共仓与本仓（本仓 conftest.py 已自动注入）。
"""

from __future__ import annotations

import unittest
from unittest import mock

from aigcnews_private.sources import x_transport
from aigcnews_private.sources.wechat import (
    account_service,
    errors,
    follow_service,
    login_service,
    sync_service,
    transport,
)
from aigcnews_private.sources.wechat_sogou import transport as sogou_transport
from backend.app.core.config import settings
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


class WeChatContractIdentityTests(unittest.TestCase):
    """私有实现与公共契约共享错误基类，并满足服务方法面 Protocol。"""

    def test_error_base_shared_with_contract(self) -> None:
        self.assertIs(errors.WeChatError, WeChatError)
        self.assertTrue(issubclass(errors.WeChatSessionExpired, WeChatError))
        self.assertTrue(issubclass(errors.WeChatUpstreamError, WeChatError))

    def test_impl_services_satisfy_protocols(self) -> None:
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


class WeChatSourceDefaultCandidateTests(_SourcePluginTestCase):
    def test_flag_on_loads_private_bundle_via_default_candidates(self) -> None:
        with mock.patch.object(settings, "wechat_source_enabled", True):
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


if __name__ == "__main__":
    unittest.main()
