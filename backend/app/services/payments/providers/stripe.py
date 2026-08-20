"""Stripe Checkout 渠道（ADR 0002，已接入真实 API，不引入 stripe SDK）。

- create_payment：POST /v1/checkout/sessions（mode=payment，metadata 带
  order_no，client_reference_id=order_no），返回 redirect_url 指令；
  渠道 4xx/5xx/网络错 → ChannelUpstreamError（路由映射 502）。
- verify_and_parse_callback：Stripe-Signature 头（t/v1）对 raw_body 原始字节
  做 HMAC-SHA256 验签（compare_digest，tolerance ±300s）；只认
  checkout.session.completed；amount_total 天然是分，currency 大写归一。
- query_order 保持桩：Stripe 没有按 client_reference_id 的干净查单 API
  （search API 需单独开通且按行计费），关单对账需求落在微信/支付宝侧。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
from urllib.parse import urlencode

import httpx
from fastapi import Response
from fastapi.responses import JSONResponse

from backend.app.services.payments.providers.base import (
    CallbackVerificationError,
    ChannelUpstreamError,
    PaymentInstruction,
    ProviderNotConfiguredError,
    VerifiedCallback,
)


class StripeProviderConfig(Protocol):
    stripe_secret_key: str
    stripe_webhook_secret: str


CHANNEL_STRIPE = "stripe"
_STRIPE_API_BASE = "https://api.stripe.com"
_WEBHOOK_TOLERANCE_SECONDS = 300
_HTTP_TIMEOUT_SECONDS = 10.0


def _product_name(order: Mapping[str, Any]) -> str:
    plan_code = str(order.get("plan_code", ""))
    if plan_code.endswith("yearly"):
        return "AIGC Radar Membership (Yearly)"
    return "AIGC Radar Membership (Monthly)"


def _return_urls(order: Mapping[str, Any], return_url: str | None) -> tuple[str | None, str | None]:
    """success/cancel 同形：回跳收银台并带 order_no+plan 供前端续单。"""
    if not return_url:
        return None, None
    order_no = str(order["order_no"])
    plan = "yearly" if str(order.get("plan_code", "")).endswith("yearly") else "monthly"
    separator = "&" if "?" in return_url else "?"
    url = f"{return_url}{separator}{urlencode({'order_no': order_no, 'plan': plan})}"
    return url, url


def _parse_signature_header(header: str) -> tuple[int | None, list[str]]:
    timestamp: int | None = None
    signatures: list[str] = []
    for part in header.split(","):
        key, _, value = part.partition("=")
        if key == "t":
            try:
                timestamp = int(value)
            except ValueError:
                timestamp = None
        elif key == "v1" and value:
            signatures.append(value)
    return timestamp, signatures


class StripePaymentProvider:
    """Stripe Checkout 渠道；凭证未齐时全部能力 503。"""

    channel = CHANNEL_STRIPE

    def __init__(self, settings: StripeProviderConfig, *, transport: httpx.BaseTransport | None = None) -> None:
        self._secret_key = getattr(settings, "stripe_secret_key", "")
        self._webhook_secret = getattr(settings, "stripe_webhook_secret", "")
        self._transport = transport

    def is_configured(self) -> bool:
        return all([self._secret_key, self._webhook_secret])

    def create_payment(
        self,
        *,
        order: Mapping[str, Any],
        notify_url: str,
        return_url: str | None,
    ) -> PaymentInstruction:
        if not self.is_configured():
            raise ProviderNotConfiguredError("stripe channel not configured")
        order_no = str(order["order_no"])
        success_url, cancel_url = _return_urls(order, return_url)
        form: dict[str, str] = {
            "mode": "payment",
            "line_items[0][price_data][currency]": str(order["currency"]).lower(),
            "line_items[0][price_data][unit_amount]": str(int(order["amount_cents"])),
            "line_items[0][price_data][product_data][name]": _product_name(order),
            "line_items[0][quantity]": "1",
            "metadata[order_no]": order_no,
            "client_reference_id": order_no,
        }
        if success_url is not None:
            form["success_url"] = success_url
        if cancel_url is not None:
            form["cancel_url"] = cancel_url
        try:
            with httpx.Client(transport=self._transport, timeout=_HTTP_TIMEOUT_SECONDS) as client:
                response = client.post(
                    f"{_STRIPE_API_BASE}/v1/checkout/sessions",
                    data=form,
                    headers={"Authorization": f"Bearer {self._secret_key}"},
                )
        except httpx.HTTPError as exc:
            raise ChannelUpstreamError(f"stripe checkout session request failed: {exc}") from exc
        if response.status_code != 200:
            raise ChannelUpstreamError(
                f"stripe checkout session rejected: HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ChannelUpstreamError("stripe checkout session returned non-JSON body") from exc
        url = payload.get("url") if isinstance(payload, dict) else None
        if not isinstance(url, str) or not url:
            raise ChannelUpstreamError("stripe checkout session missing url")
        return PaymentInstruction(kind="redirect_url", content=url)

    def verify_and_parse_callback(
        self,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> VerifiedCallback:
        if not self.is_configured():
            raise ProviderNotConfiguredError("stripe channel not configured")
        signature_header = next(
            (value for key, value in headers.items() if key.lower() == "stripe-signature"),
            "",
        )
        timestamp, signatures = _parse_signature_header(signature_header)
        if timestamp is None or not signatures:
            raise CallbackVerificationError("missing stripe signature header")
        if abs(time.time() - timestamp) > _WEBHOOK_TOLERANCE_SECONDS:
            raise CallbackVerificationError("stripe webhook timestamp outside tolerance")
        expected = hmac.new(
            self._webhook_secret.encode("utf-8"),
            f"{timestamp}.".encode("utf-8") + raw_body,
            hashlib.sha256,
        ).hexdigest()
        if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
            raise CallbackVerificationError("stripe webhook signature mismatch")

        try:
            event = json.loads(raw_body)
        except ValueError as exc:
            raise CallbackVerificationError("invalid stripe event payload") from exc
        if not isinstance(event, dict) or event.get("type") != "checkout.session.completed":
            raise CallbackVerificationError("unsupported stripe event type")
        data = event.get("data")
        session = data.get("object") if isinstance(data, dict) else None
        if not isinstance(session, dict):
            raise CallbackVerificationError("stripe session payload missing object")
        metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
        order_no = metadata.get("order_no")
        amount_total = session.get("amount_total")
        currency = session.get("currency")
        payment_intent = session.get("payment_intent")
        if (
            not order_no
            or not isinstance(amount_total, int)
            or not isinstance(currency, str)
            or not currency
            or not payment_intent
        ):
            raise CallbackVerificationError("stripe session missing required fields")

        created = event.get("created")
        if isinstance(created, (int, float)):
            paid_at = datetime.fromtimestamp(int(created), tz=timezone.utc)
        else:
            paid_at = datetime.now(timezone.utc)
        return VerifiedCallback(
            order_no=str(order_no),
            channel_order_no=str(payment_intent),
            amount_cents=int(amount_total),
            currency=currency.upper(),
            paid_at=paid_at,
        )

    def build_ack_response(self, *, ok: bool) -> Response:
        # Stripe 应答契约：2xx 即成功；非 2xx 会按指数退避重发。
        return JSONResponse({}, status_code=200 if ok else 400)

    def query_order(self, *, order: Mapping[str, Any]) -> str:
        # Stripe 无按 client_reference_id 的干净查单 API（search 需单独开通），
        # 关单对账需求落在微信/支付宝侧；保持桩语义。
        raise ProviderNotConfiguredError("stripe query_order not supported")
