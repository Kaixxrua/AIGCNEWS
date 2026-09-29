"""可选采集源（X）的公开契约与装配入口。

X transport 随公共仓发布，默认关闭（``x_source_enabled``），开启后由 loader
fail-closed 装配。调用方只依赖本包暴露的异常、常量与 Protocol。
"""

from backend.app.services.source_plugins.loader import load_x_transport_class
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
    "XAuthAbort",
    "XAuthNotConfigured",
    "XRateLimitAbort",
    "XTransportProtocol",
    "XTransportUnavailable",
    "load_x_transport_class",
]
