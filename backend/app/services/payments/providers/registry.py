"""支付渠道注册表：按 settings 构建全部渠道桩（ADR 0002）。

请求时从 settings 单例构建（纯配置读取，成本可忽略；与 feature_gates
请求时读 settings 的先例一致，测试可经 dependency_overrides 翻转）。
"""

from __future__ import annotations

from typing import Protocol


class PaymentProviderConfig(Protocol):
    stripe_secret_key: str
    stripe_webhook_secret: str

from backend.app.services.payments.providers.alipay_page import (
    AlipayPagePaymentProvider,
)
from backend.app.services.payments.providers.base import PaymentProvider
from backend.app.services.payments.providers.stripe import StripePaymentProvider
from backend.app.services.payments.providers.wechat_native import (
    WeChatNativePaymentProvider,
)


def build_payment_providers(config: PaymentProviderConfig) -> dict[str, PaymentProvider]:
    providers = (
        WeChatNativePaymentProvider(config),
        AlipayPagePaymentProvider(config),
        StripePaymentProvider(config),
    )
    return {provider.channel: provider for provider in providers}
