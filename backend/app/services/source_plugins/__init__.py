"""可选采集源（X / 微信公众号）的公开契约与装配入口。

X transport 随公共仓发布，微信公众号实现仍由仓库外私有包
``aigcnews_private`` 提供。两者默认关闭（``x_source_enabled`` /
``wechat_source_enabled``），开启后由 loader fail-closed 装配。调用方只依赖
本包暴露的异常、常量与 Protocol。
"""

from backend.app.services.source_plugins.loader import (
    load_wechat_bundle,
    load_x_transport_class,
)
from backend.app.services.source_plugins.wechat_source import (
    WeChatAccountServiceProtocol,
    WeChatError,
    WeChatFollowServiceProtocol,
    WeChatLoginServiceProtocol,
    WeChatServiceBundle,
    WeChatSyncServiceProtocol,
)
from backend.app.services.source_plugins.x_source import (
    DEFAULT_INTER_ACCOUNT_DELAY,
    XAuthAbort,
    XAuthNotConfigured,
    XRateLimitAbort,
    XTransportProtocol,
    XTransportUnavailable,
)

__all__ = [
    "DEFAULT_INTER_ACCOUNT_DELAY",
    "WeChatAccountServiceProtocol",
    "WeChatError",
    "WeChatFollowServiceProtocol",
    "WeChatLoginServiceProtocol",
    "WeChatServiceBundle",
    "WeChatSyncServiceProtocol",
    "XAuthAbort",
    "XAuthNotConfigured",
    "XRateLimitAbort",
    "XTransportProtocol",
    "XTransportUnavailable",
    "load_wechat_bundle",
    "load_x_transport_class",
]
