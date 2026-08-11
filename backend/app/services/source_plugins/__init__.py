"""可插拔采集源（X / 微信公众号）的公开契约与加载器。

X 与微信公众号链路涉及平台侧敏感实现（私有端点、响应结构解析、
扫码登录流程等），以插件形式提供：默认关闭（``x_source_enabled`` /
``wechat_source_enabled``），开启后经 loader 按候选模块顺序加载——
优先仓库外私有包 ``aigcnews_private``，回退仓库内过渡期实现。
公共代码只依赖本包暴露的异常、常量与 Protocol。
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
