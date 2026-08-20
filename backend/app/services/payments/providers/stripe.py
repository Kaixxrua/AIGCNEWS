"""Stripe（国际卡）渠道桩（ADR 0002）。

凭证就绪后接入点（骨架期刻意留空）：
- create_payment：Checkout Session（mode=payment，metadata 带 order_no），
  返回 redirect_url 指令（骨架期不引入 stripe SDK，直接 HTTP API 即可）；
- verify_and_parse_callback：Stripe-Signature 头对 raw_body 原始字节做
  HMAC-SHA256 验签 + tolerance 时间窗，取 checkout.session.completed 事件的
  metadata.order_no / payment_intent / amount_total（cents，天然是分）。
"""

from __future__ import annotations

from typing import Any, Mapping

from fastapi import Response
from fastapi.responses import JSONResponse

from typing import Protocol


class StripeProviderConfig(Protocol):
    stripe_secret_key: str
    stripe_webhook_secret: str

from backend.app.services.payments.providers.base import (
    PaymentInstruction,
    ProviderNotConfiguredError,
    VerifiedCallback,
)

CHANNEL_STRIPE = "stripe"


class StripePaymentProvider:
    """Stripe Checkout 渠道；凭证未齐时全部能力 503。"""

    channel = CHANNEL_STRIPE

    def __init__(self, settings: StripeProviderConfig) -> None:
        self._settings = settings

    def is_configured(self) -> bool:
        return all(
            [
                getattr(self._settings, "stripe_secret_key", ""),
                getattr(self._settings, "stripe_webhook_secret", ""),
            ]
        )

    def create_payment(
        self,
        *,
        order: Mapping[str, Any],
        notify_url: str,
        return_url: str | None,
    ) -> PaymentInstruction:
        # TODO(渠道接入 PR)：POST /v1/checkout/sessions → PaymentInstruction("redirect_url", session.url)
        raise ProviderNotConfiguredError("stripe channel credentials pending")

    def verify_and_parse_callback(
        self,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> VerifiedCallback:
        # TODO(渠道接入 PR)：Stripe-Signature HMAC 验签（原始字节 + tolerance）
        # → checkout.session.completed → metadata.order_no / amount_total
        raise ProviderNotConfiguredError("stripe channel credentials pending")

    def build_ack_response(self, *, ok: bool) -> Response:
        # Stripe 应答契约：2xx 即成功；非 2xx 会按指数退避重发。
        return JSONResponse({}, status_code=200 if ok else 400)

    def query_order(self, *, order: Mapping[str, Any]) -> str:
        # TODO(渠道接入 PR)：GET /v1/checkout/sessions/{id} 或 payment_intent 检索
        raise ProviderNotConfiguredError("stripe channel credentials pending")
