"""PayPal 收单渠道（overseas_redirect 的服务商实现之一，v2 Orders REST，无 SDK）。

通用凭证槽在本服务商下的语义（配置面板/文档的「海外支付」区）：
- overseas_client_id      → PayPal Client ID
- overseas_client_secret  → PayPal Secret（OAuth client-credentials）
- overseas_webhook_secret → Webhook ID（开发者后台订阅 webhook 后分配，
  用作 verify-webhook-signature 的 webhook_id 参数）
- overseas_sandbox        → 切 api-m.sandbox.paypal.com / api-m.paypal.com

- create_payment：每次调用现场取 OAuth token（无状态不缓存）→
  POST /v2/checkout/orders（intent=CAPTURE，purchase_unit 的
  reference_id/custom_id 均 = order_no，PayPal-Request-Id=order_no 幂等；
  金额/币种按订单快照透传，provider 不做币种假设——CNY 受理范围受 PayPal
  跨境限制，见 docs/payments.md）→ 取 links 中 rel=approve 的 href →
  redirect_url 指令。
- verify_and_parse_callback：transmission_* 五头 + webhook_id 调
  /v1/notifications/verify-webhook-signature 服务端验签（验签调用本身的
  上游故障抛 ChannelUpstreamError → 路由 5xx → PayPal 按重试策略重发），
  verification_status == SUCCESS 才受理；
  · CHECKOUT.ORDER.APPROVED → 服务端立即 capture（失败抛
    ChannelUpstreamError，同样靠 PayPal 重发补偿），随后
    PAYMENT.CAPTURE.COMPLETED 事件负责落账，本事件返回 None；
  · PAYMENT.CAPTURE.COMPLETED → resource.custom_id 取 order_no、金额串
    fail-closed 归一到分、supplementary_data.related_ids.order_id 作为
    渠道单号（缺省退 capture id）→ VerifiedCallback；
  · 其余事件 → None（验签通过但非终态，路由 ACK 200 零状态变更）。
- query_order：GET /v2/checkout/orders/{channel_order_no}，返回 status
  原串；未绑定渠道单号抛 ProviderNotConfiguredError（骨架期不进路由，
  见 base.py 契约）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
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
from backend.app.services.payments.providers.overseas_redirect import (
    CHANNEL_OVERSEAS_REDIRECT,
)


class PayPalProviderConfig(Protocol):
    overseas_provider: str
    overseas_sandbox: bool
    overseas_client_id: str
    overseas_client_secret: str
    overseas_webhook_secret: str


_SANDBOX_API_BASE = "https://api-m.sandbox.paypal.com"
_LIVE_API_BASE = "https://api-m.paypal.com"
_HTTP_TIMEOUT_SECONDS = 10.0
_EVENT_ORDER_APPROVED = "CHECKOUT.ORDER.APPROVED"
_EVENT_CAPTURE_COMPLETED = "PAYMENT.CAPTURE.COMPLETED"
_VERIFICATION_SUCCESS = "SUCCESS"


def _product_name(order: Mapping[str, Any]) -> str:
    plan_code = str(order.get("plan_code", ""))
    if plan_code.endswith("yearly"):
        return "AIGC Radar Membership (Yearly)"
    return "AIGC Radar Membership (Monthly)"


def _return_urls(order: Mapping[str, Any], return_url: str | None) -> tuple[str | None, str | None]:
    """return/cancel 同形：回跳收银台并带 order_no+plan 供前端续单。"""
    if not return_url:
        return None, None
    order_no = str(order["order_no"])
    plan = "yearly" if str(order.get("plan_code", "")).endswith("yearly") else "monthly"
    separator = "&" if "?" in return_url else "?"
    url = f"{return_url}{separator}{urlencode({'order_no': order_no, 'plan': plan})}"
    return url, url


def _amount_value(amount_cents: object) -> str:
    """分 → PayPal 金额串（两位小数；币种小数位假设与支付宝渠道一致）。"""
    try:
        cents = int(amount_cents)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid payment amount") from exc
    if cents <= 0:
        raise ValueError("payment amount must be positive")
    return f"{Decimal(cents) / Decimal(100):.2f}"


def _amount_to_cents(value: object) -> int:
    """PayPal 金额串 fail-closed 归一到分；非有限/非正/不可整除一律拒绝。"""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CallbackVerificationError("invalid paypal capture amount") from exc
    if not amount.is_finite() or amount <= 0:
        raise CallbackVerificationError("paypal capture amount must be positive")
    cents = amount * 100
    if cents != cents.to_integral_value():
        raise CallbackVerificationError("paypal capture amount is not representable in cents")
    return int(cents)


def _parse_paypal_time(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise CallbackVerificationError("missing paypal capture create_time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CallbackVerificationError("invalid paypal capture create_time") from exc
    if parsed.tzinfo is None:
        raise CallbackVerificationError("paypal create_time must carry a timezone")
    return parsed.astimezone(timezone.utc)


class PayPalProvider:
    """PayPal v2 Orders 渠道；凭证未齐时全部能力 503。"""

    channel = CHANNEL_OVERSEAS_REDIRECT

    def __init__(
        self,
        settings: PayPalProviderConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client_id = str(getattr(settings, "overseas_client_id", "") or "")
        self._client_secret = str(getattr(settings, "overseas_client_secret", "") or "")
        self._webhook_id = str(getattr(settings, "overseas_webhook_secret", "") or "")
        self._sandbox = bool(getattr(settings, "overseas_sandbox", False))
        self._transport = transport

    def is_configured(self) -> bool:
        return all([self._client_id, self._client_secret, self._webhook_id])

    def _api_base(self) -> str:
        return _SANDBOX_API_BASE if self._sandbox else _LIVE_API_BASE

    def _client(self) -> httpx.Client:
        return httpx.Client(transport=self._transport, timeout=_HTTP_TIMEOUT_SECONDS)

    def _oauth_token(self, client: httpx.Client) -> str:
        try:
            response = client.post(
                f"{self._api_base()}/v1/oauth2/token",
                data={"grant_type": "client_credentials"},
                auth=(self._client_id, self._client_secret),
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise ChannelUpstreamError(f"paypal oauth request failed: {exc}") from exc
        if response.status_code != 200:
            raise ChannelUpstreamError(
                f"paypal oauth rejected: HTTP {response.status_code}"
            )
        try:
            payload = response.json()
            token = payload["access_token"]
            if not isinstance(token, str) or not token:
                raise TypeError
        except (ValueError, KeyError, TypeError) as exc:
            raise ChannelUpstreamError("paypal oauth returned no access_token") from exc
        return token

    def create_payment(
        self,
        *,
        order: Mapping[str, Any],
        notify_url: str,
        return_url: str | None,
        shopper_ip: str | None = None,
    ) -> PaymentInstruction:
        del shopper_ip  # PayPal 无需下单人 IP（PingPong 才需要）
        if not self.is_configured():
            raise ProviderNotConfiguredError("overseas_redirect(paypal) channel not configured")
        order_no = str(order["order_no"])
        success_url, cancel_url = _return_urls(order, return_url)
        purchase_unit: dict[str, Any] = {
            "reference_id": order_no,
            "custom_id": order_no,
            "amount": {
                "currency_code": str(order["currency"]).upper(),
                "value": _amount_value(order["amount_cents"]),
            },
            "description": _product_name(order),
        }
        application_context: dict[str, Any] = {
            "brand_name": "AIGC Radar",
            "user_action": "PAY_NOW",
        }
        if success_url is not None:
            application_context["return_url"] = success_url
        if cancel_url is not None:
            application_context["cancel_url"] = cancel_url
        body = {
            "intent": "CAPTURE",
            "purchase_units": [purchase_unit],
            "application_context": application_context,
        }
        try:
            with self._client() as client:
                token = self._oauth_token(client)
                response = client.post(
                    f"{self._api_base()}/v2/checkout/orders",
                    content=json.dumps(body).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "PayPal-Request-Id": order_no,
                    },
                )
        except httpx.HTTPError as exc:
            raise ChannelUpstreamError(f"paypal order request failed: {exc}") from exc
        if response.status_code not in (200, 201):
            raise ChannelUpstreamError(
                f"paypal order rejected: HTTP {response.status_code}"
            )
        try:
            payload = response.json()
            links = payload["links"]
            if not isinstance(links, list):
                raise TypeError
        except (ValueError, KeyError, TypeError) as exc:
            raise ChannelUpstreamError("paypal order returned invalid payload") from exc
        approve_url = next(
            (
                link.get("href")
                for link in links
                if isinstance(link, dict) and link.get("rel") == "approve"
            ),
            None,
        )
        if not isinstance(approve_url, str) or not approve_url:
            raise ChannelUpstreamError("paypal order missing approve link")
        return PaymentInstruction(kind="redirect_url", content=approve_url)

    def verify_and_parse_callback(
        self,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> VerifiedCallback | None:
        if not self.is_configured():
            raise ProviderNotConfiguredError("overseas_redirect(paypal) channel not configured")
        header_map = {key.lower(): value for key, value in headers.items()}
        transmission_id = header_map.get("paypal-transmission-id", "")
        transmission_time = header_map.get("paypal-transmission-time", "")
        transmission_sig = header_map.get("paypal-transmission-sig", "")
        cert_url = header_map.get("paypal-cert-url", "")
        auth_algo = header_map.get("paypal-auth-algo", "")
        if not all([transmission_id, transmission_time, transmission_sig, cert_url, auth_algo]):
            raise CallbackVerificationError("missing paypal transmission headers")
        try:
            event = json.loads(raw_body)
        except ValueError as exc:
            raise CallbackVerificationError("invalid paypal event payload") from exc
        if not isinstance(event, dict):
            raise CallbackVerificationError("invalid paypal event payload")
        self._verify_webhook_signature(
            event,
            transmission_id=transmission_id,
            transmission_time=transmission_time,
            transmission_sig=transmission_sig,
            cert_url=cert_url,
            auth_algo=auth_algo,
        )

        event_type = event.get("event_type")
        resource = event.get("resource")
        if not isinstance(resource, dict):
            raise CallbackVerificationError("paypal event missing resource")
        if event_type == _EVENT_ORDER_APPROVED:
            order_id = resource.get("id")
            if not isinstance(order_id, str) or not order_id:
                raise CallbackVerificationError("paypal approved event missing order id")
            order_no = self._order_no_from_purchase_units(resource) or order_id
            self._capture_order(paypal_order_id=order_id, request_id=order_no)
            return None
        if event_type != _EVENT_CAPTURE_COMPLETED:
            return None
        order_no = resource.get("custom_id")
        if not isinstance(order_no, str) or not order_no:
            raise CallbackVerificationError("paypal capture missing custom_id")
        amount = resource.get("amount")
        if not isinstance(amount, Mapping):
            raise CallbackVerificationError("paypal capture missing amount")
        currency_code = amount.get("currency_code")
        if not isinstance(currency_code, str) or not currency_code:
            raise CallbackVerificationError("paypal capture missing currency_code")
        capture_id = resource.get("id")
        channel_order_no = self._channel_order_no(resource, fallback=capture_id)
        if not channel_order_no:
            raise CallbackVerificationError("paypal capture missing order identifiers")
        return VerifiedCallback(
            order_no=order_no,
            channel_order_no=channel_order_no,
            amount_cents=_amount_to_cents(amount.get("value")),
            currency=currency_code.upper(),
            paid_at=_parse_paypal_time(resource.get("create_time") or event.get("create_time")),
        )

    @staticmethod
    def _order_no_from_purchase_units(resource: Mapping[str, Any]) -> str:
        purchase_units = resource.get("purchase_units")
        if not isinstance(purchase_units, list) or not purchase_units:
            return ""
        unit = purchase_units[0]
        if not isinstance(unit, dict):
            return ""
        return str(unit.get("custom_id") or unit.get("reference_id") or "")

    @staticmethod
    def _channel_order_no(resource: Mapping[str, Any], *, fallback: object) -> str:
        supplementary = resource.get("supplementary_data")
        if isinstance(supplementary, Mapping):
            related_ids = supplementary.get("related_ids")
            if isinstance(related_ids, Mapping):
                order_id = related_ids.get("order_id")
                if isinstance(order_id, str) and order_id:
                    return order_id
        return str(fallback or "")

    def _verify_webhook_signature(
        self,
        event: Mapping[str, Any],
        *,
        transmission_id: str,
        transmission_time: str,
        transmission_sig: str,
        cert_url: str,
        auth_algo: str,
    ) -> None:
        body = {
            "auth_algo": auth_algo,
            "cert_url": cert_url,
            "transmission_id": transmission_id,
            "transmission_sig": transmission_sig,
            "transmission_time": transmission_time,
            "webhook_id": self._webhook_id,
            "webhook_event": event,
        }
        try:
            with self._client() as client:
                token = self._oauth_token(client)
                response = client.post(
                    f"{self._api_base()}/v1/notifications/verify-webhook-signature",
                    content=json.dumps(body).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            raise ChannelUpstreamError(f"paypal webhook verify request failed: {exc}") from exc
        if response.status_code != 200:
            raise ChannelUpstreamError(
                f"paypal webhook verify rejected: HTTP {response.status_code}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise ChannelUpstreamError("paypal webhook verify returned non-JSON body") from exc
        if not isinstance(payload, dict) or payload.get("verification_status") != _VERIFICATION_SUCCESS:
            raise CallbackVerificationError("paypal webhook signature verification failed")

    def _capture_order(self, *, paypal_order_id: str, request_id: str) -> None:
        try:
            with self._client() as client:
                token = self._oauth_token(client)
                response = client.post(
                    f"{self._api_base()}/v2/checkout/orders/{paypal_order_id}/capture",
                    content=b"{}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "PayPal-Request-Id": f"{request_id}-capture",
                    },
                )
        except httpx.HTTPError as exc:
            raise ChannelUpstreamError(f"paypal capture request failed: {exc}") from exc
        if response.status_code not in (200, 201):
            raise ChannelUpstreamError(
                f"paypal capture rejected: HTTP {response.status_code}"
            )

    def build_ack_response(self, *, ok: bool) -> Response:
        # PayPal 应答契约：2xx 即成功；非 2xx 会按渠道策略重发通知。
        return JSONResponse({}, status_code=200 if ok else 400)

    def query_order(self, *, order: Mapping[str, Any]) -> str:
        if not self.is_configured():
            raise ProviderNotConfiguredError("overseas_redirect(paypal) channel not configured")
        channel_order_no = str(order.get("channel_order_no") or "")
        if not channel_order_no:
            raise ProviderNotConfiguredError("paypal order is not bound to a channel order no")
        try:
            with self._client() as client:
                token = self._oauth_token(client)
                response = client.get(
                    f"{self._api_base()}/v2/checkout/orders/{channel_order_no}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            raise ChannelUpstreamError(f"paypal order query request failed: {exc}") from exc
        if response.status_code != 200:
            raise ChannelUpstreamError(
                f"paypal order query rejected: HTTP {response.status_code}"
            )
        try:
            payload = response.json()
            status_value = payload["status"]
            if not isinstance(status_value, str) or not status_value:
                raise TypeError
        except (ValueError, KeyError, TypeError) as exc:
            raise ChannelUpstreamError("paypal order query returned invalid response") from exc
        return status_value
