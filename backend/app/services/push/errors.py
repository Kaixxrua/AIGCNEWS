"""订阅推送领域错误。

detail 为可安全回显给客户端的文案；HTTP 状态码由路由层映射，
服务层不感知传输协议。
"""

from __future__ import annotations


class PushDomainError(Exception):
    code = "push-error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class VipRequiredError(PushDomainError):
    code = "vip-required"


class InvalidProviderTargetError(PushDomainError):
    code = "invalid-provider-target"


class ProviderRateLimitedError(PushDomainError):
    code = "provider-rate-limited"


class ProviderCredentialInvalidError(PushDomainError):
    code = "provider-credential-invalid"


class TelegramNotConfiguredError(PushDomainError):
    """Telegram 推送未在部署侧启用（路由层映射 503）。"""

    code = "telegram-not-configured"


class TelegramDeliveryError(PushDomainError):
    """Telegram Bot API 运行时投递失败（路由层映射 502）。"""

    code = "telegram-delivery-failed"


class PushChannelNotFoundError(PushDomainError):
    """渠道不存在或不属于当前用户（路由层映射 404）。"""


class PushChannelDuplicateError(PushDomainError):
    """同一用户同一渠道类型下目标已绑定（路由层映射 409）。"""


class PushChannelNotVerifiedError(PushDomainError):
    """渠道尚未通过验证码校验（路由层映射 400）。"""


class PushChannelDisabledError(PushDomainError):
    """渠道已停用（路由层映射 400）。"""


class InvalidChannelOtpError(PushDomainError):
    """渠道绑定验证码错误或已过期（路由层映射 400）。"""


class WebhookUrlError(PushDomainError):
    """Webhook URL 非法或不在允许范围（路由层映射 400）。"""


class WebhookProbeFailedError(PushDomainError):
    """Webhook 创建前探测投递失败（路由层映射 400）。"""


class WebhookDeliveryError(PushDomainError):
    """Webhook 运行时投递失败（路由层映射 502）。"""


class SubscriptionNotFoundError(PushDomainError):
    """订阅不存在或不属于当前用户（路由层映射 404）。"""


class SubscriptionDuplicateError(PushDomainError):
    """同一渠道下来源与频率组合已订阅（路由层映射 409）。"""
