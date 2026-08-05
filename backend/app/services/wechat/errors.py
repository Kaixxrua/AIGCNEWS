from __future__ import annotations


class WeChatError(Exception):
    """Base class for all WeChat backend domain errors."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class WeChatAuthRequired(WeChatError):
    def __init__(self, message: str = "需要重新扫描二维码登录微信") -> None:
        super().__init__("WECHAT_LOGIN_REQUIRED", message)


class WeChatSessionExpired(WeChatError):
    def __init__(self, message: str = "微信会话已失效，请重新扫码") -> None:
        super().__init__("WECHAT_SESSION_EXPIRED", message)


class WeChatQrExpired(WeChatError):
    def __init__(self, message: str = "二维码已过期，请刷新") -> None:
        super().__init__("WECHAT_QR_EXPIRED", message)


class WeChatLoginPending(WeChatError):
    def __init__(self, message: str = "微信登录仍在等待") -> None:
        super().__init__("WECHAT_LOGIN_PENDING", message)


class WeChatLoginFailed(WeChatError):
    def __init__(self, message: str = "微信登录失败") -> None:
        super().__init__("WECHAT_LOGIN_FAILED", message)


class WeChatProxyError(WeChatError):
    def __init__(self, message: str = "代理不可用或目标连接失败") -> None:
        super().__init__("WECHAT_PROXY_UNAVAILABLE", message)


class WeChatRateLimited(WeChatError):
    def __init__(self, message: str = "微信请求过于频繁") -> None:
        super().__init__("WECHAT_RATE_LIMITED", message)


class WeChatUpstreamError(WeChatError):
    def __init__(self, message: str = "微信上游返回异常") -> None:
        super().__init__("WECHAT_UPSTREAM_ERROR", message)


class WeChatAccountNotFound(WeChatError):
    def __init__(self, message: str = "公众号不存在") -> None:
        super().__init__("WECHAT_ACCOUNT_NOT_FOUND", message)


class WeChatSyncRunning(WeChatError):
    def __init__(self, message: str = "同步任务正在运行") -> None:
        super().__init__("WECHAT_SYNC_RUNNING", message)
