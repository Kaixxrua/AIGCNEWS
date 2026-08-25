"""支付渠道注册表：按 settings 构建全部渠道桩（ADR 0002）。

请求时从 settings 单例构建（纯配置读取，成本可忽略；与 feature_gates
请求时读 settings 的先例一致，测试可经 dependency_overrides 翻转）。

海外渠道单槽分发：``config.overseas_provider`` 选服务商
（paypal / pingpong），未选或未知值一律落 UnselectedOverseasProvider
fail-closed 桩——渠道 id 恒为 overseas_redirect，绝不 KeyError。
"""

from __future__ import annotations

from typing import Protocol


class PaymentProviderConfig(Protocol):
    overseas_provider: str
    overseas_sandbox: bool
    overseas_client_id: str
    overseas_client_secret: str
    overseas_webhook_secret: str
    public_base_url: str

from backend.app.services.payments.providers.alipay_page import (
    AlipayPagePaymentProvider,
)
from backend.app.services.payments.providers.base import PaymentProvider
from backend.app.services.payments.providers.overseas_redirect import (
    UnselectedOverseasProvider,
)
from backend.app.services.payments.providers.paypal import PayPalProvider
from backend.app.services.payments.providers.pingpong import PingPongProvider
from backend.app.services.payments.providers.wechat_native import (
    WeChatNativePaymentProvider,
)


def _build_overseas_provider(config: PaymentProviderConfig) -> PaymentProvider:
    provider_name = str(getattr(config, "overseas_provider", "") or "").strip().lower()
    if provider_name == "paypal":
        return PayPalProvider(config)
    if provider_name == "pingpong":
        return PingPongProvider(config)
    return UnselectedOverseasProvider(config)


def build_payment_providers(config: PaymentProviderConfig) -> dict[str, PaymentProvider]:
    providers = (
        WeChatNativePaymentProvider(config),
        AlipayPagePaymentProvider(config),
        _build_overseas_provider(config),
    )
    return {provider.channel: provider for provider in providers}
