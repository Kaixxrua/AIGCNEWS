"""海外跳转收单渠道（ADR 0002）：渠道常量与「未选服务商」fail-closed 桩。

渠道 id 统一为 ``overseas_redirect``，由 registry 按
``config.overseas_provider`` 分发到具体服务商实现（paypal / pingpong）；
服务商未选择或值未知时落本桩：is_configured 恒 False、全方法抛
ProviderNotConfiguredError，绝不 KeyError/半初始化。
"""

from __future__ import annotations

from typing import Any, Mapping

from fastapi import Response
from fastapi.responses import JSONResponse

from backend.app.services.payments.providers.base import (
    PaymentInstruction,
    ProviderNotConfiguredError,
    VerifiedCallback,
)

CHANNEL_OVERSEAS_REDIRECT = "overseas_redirect"


class UnselectedOverseasProvider:
    """未选海外服务商的 fail-closed 桩；渠道对外表现为「即将开放」。"""

    channel = CHANNEL_OVERSEAS_REDIRECT

    def __init__(self, settings: object | None = None) -> None:
        # 与具体服务商保持同形构造（registry 统一传 config）；桩不读任何配置。
        del settings

    def is_configured(self) -> bool:
        return False

    def create_payment(
        self,
        *,
        order: Mapping[str, Any],
        notify_url: str,
        return_url: str | None,
        shopper_ip: str | None = None,
    ) -> PaymentInstruction:
        raise ProviderNotConfiguredError("overseas provider is not selected")

    def verify_and_parse_callback(
        self,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> VerifiedCallback | None:
        raise ProviderNotConfiguredError("overseas provider is not selected")

    def build_ack_response(self, *, ok: bool) -> Response:
        # 未选服务商时渠道不会发来回调（无凭证可配 notificationUrl）；
        # 形状仅作兜底，对齐 2xx=成功 / 4xx=失败 的通用应答。
        return JSONResponse({}, status_code=200 if ok else 400)

    def query_order(self, *, order: Mapping[str, Any]) -> str:
        raise ProviderNotConfiguredError("overseas provider is not selected")
