from __future__ import annotations


class SogouWechatError(Exception):
    """Base class for Sogou WeChat public-index errors."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class SogouBlockedError(SogouWechatError):
    """Sogou anti-spider intercepted the request (captcha / antispider page)."""

    def __init__(self, message: str = "搜狗微信反爬拦截，请稍后再试") -> None:
        super().__init__("SOGOU_WECHAT_BLOCKED", message)


class SogouUpstreamError(SogouWechatError):
    """Sogou returned an unexpected response."""

    def __init__(self, message: str = "搜狗微信上游返回异常") -> None:
        super().__init__("SOGOU_WECHAT_UPSTREAM_ERROR", message)
