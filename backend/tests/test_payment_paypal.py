"""PayPal v2 Orders 渠道契约测试（overseas_redirect 服务商实现之一）。

钉住的对外语义：
- 下单报文：intent=CAPTURE、reference_id/custom_id=order_no、
  PayPal-Request-Id 幂等头、approve 链接提取为 redirect_url 指令；
- 回调验签：transmission_* 五头 + webhook_id 走服务端
  verify-webhook-signature，verification_status != SUCCESS 即拒；
- 事件分派：APPROVED → 服务端 capture 后返回 None（已 capture，等
  CAPTURE.COMPLETED 落账）；COMPLETED → VerifiedCallback（金额串
  fail-closed 归一到分）；其余事件 → None（路由 ACK 200 零状态变更）；
- ACK 形状：2xx {} / 400 {}（PayPal 按状态码决定重发）；
- 凭证不齐 → 全部能力 ProviderNotConfiguredError（路由 503）。
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from backend.app.services.payments.providers.base import (
    CallbackVerificationError,
    ChannelUpstreamError,
    ProviderNotConfiguredError,
)
from backend.app.services.payments.providers.paypal import (
    PayPalProvider,
    _amount_to_cents,
    _amount_value,
    _parse_paypal_time,
)

CLIENT_ID = "paypal-client-id"
CLIENT_SECRET = "paypal-client-secret"
WEBHOOK_ID = "WH-TEST-123"
ORDER = {
    "order_no": "P20260825120000ABC123",
    "plan_code": "member_yearly",
    "amount_cents": 15900,
    "currency": "usd",
}

TRANSMISSION_HEADERS = {
    "paypal-transmission-id": "tid-123",
    "paypal-transmission-time": "2026-08-25T12:00:00Z",
    "paypal-transmission-sig": "sig-abc",
    "paypal-cert-url": "https://api-m.sandbox.paypal.com/cert.pem",
    "paypal-auth-algo": "SHA256withRSA",
}


def _provider(
    transport: httpx.BaseTransport | None = None,
    *,
    sandbox: bool = True,
    client_secret: str = CLIENT_SECRET,
    webhook_id: str = WEBHOOK_ID,
) -> PayPalProvider:
    return PayPalProvider(
        SimpleNamespace(
            overseas_provider="paypal",
            overseas_sandbox=sandbox,
            overseas_client_id=CLIENT_ID,
            overseas_client_secret=client_secret,
            overseas_webhook_secret=webhook_id,
        ),
        transport=transport,
    )


class _PayPalApi:
    """编排化的 PayPal 上游替身：记录请求、按场景应答。"""

    def __init__(
        self,
        *,
        order_status: int = 201,
        order_payload: dict | None = None,
        verification_status: str = "SUCCESS",
        capture_status: int = 201,
    ) -> None:
        self.order_status = order_status
        self.order_payload = order_payload or {
            "id": "5O190127TN364715T",
            "links": [
                {"rel": "self", "href": "https://api-m.sandbox.paypal.com/v2/checkout/orders/5O190127TN364715T"},
                {"rel": "approve", "href": "https://www.sandbox.paypal.com/checkoutnow?token=5O190127TN364715T"},
            ],
        }
        self.verification_status = verification_status
        self.capture_status = capture_status
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": f"tok-{len(self.requests)}"})
        if path == "/v2/checkout/orders":
            return httpx.Response(self.order_status, json=self.order_payload)
        if path == "/v1/notifications/verify-webhook-signature":
            return httpx.Response(200, json={"verification_status": self.verification_status})
        if path.endswith("/capture"):
            return httpx.Response(self.capture_status, json={"status": "COMPLETED"})
        if path.startswith("/v2/checkout/orders/"):
            return httpx.Response(200, json={"status": "COMPLETED"})
        raise AssertionError(f"unexpected upstream path: {path}")


def _capture_completed_event(*, order: dict = ORDER, value: str | None = None) -> dict:
    return {
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "create_time": "2026-08-25T12:30:00Z",
        "resource": {
            "id": "CAPTURE-9F1",
            "custom_id": order["order_no"],
            "amount": {
                "value": value or f"{order['amount_cents'] / 100:.2f}",
                "currency_code": order["currency"],
            },
            "create_time": "2026-08-25T12:30:00Z",
            "supplementary_data": {"related_ids": {"order_id": "5O190127TN364715T"}},
        },
    }


# ── 下单报文 ─────────────────────────────────────────────────────────────


def test_create_payment_posts_order_and_extracts_approve_link() -> None:
    api = _PayPalApi()
    instruction = _provider(api.transport()).create_payment(
        order=ORDER,
        notify_url="https://pay.example.test/api/payments/callback/overseas_redirect",
        return_url="https://pay.example.test/membership/checkout",
        shopper_ip="203.0.113.7",  # PayPal 忽略之（PingPong 才必填）
    )

    assert instruction.kind == "redirect_url"
    assert instruction.content == "https://www.sandbox.paypal.com/checkoutnow?token=5O190127TN364715T"

    assert len(api.requests) == 2
    oauth, order_req = api.requests
    assert str(oauth.url) == "https://api-m.sandbox.paypal.com/v1/oauth2/token"
    # Basic auth 头 = base64(client_id:client_secret)
    expected_basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    assert oauth.headers["Authorization"] == f"Basic {expected_basic}"
    assert oauth.content == b"grant_type=client_credentials"

    assert str(order_req.url) == "https://api-m.sandbox.paypal.com/v2/checkout/orders"
    assert order_req.headers["Authorization"].startswith("Bearer tok-")
    # 幂等头 = order_no（渠道侧同键幂等重放安全）
    assert order_req.headers["PayPal-Request-Id"] == ORDER["order_no"]
    body = json.loads(order_req.content)
    assert body["intent"] == "CAPTURE"
    unit = body["purchase_units"][0]
    assert unit["reference_id"] == ORDER["order_no"]
    assert unit["custom_id"] == ORDER["order_no"]
    # 金额按订单快照透传：分 → 两位小数串，币种 upper
    assert unit["amount"] == {"currency_code": "USD", "value": "159.00"}
    assert unit["description"] == "AIGC Radar Membership (Yearly)"
    context = body["application_context"]
    assert context["brand_name"] == "AIGC Radar"
    assert context["user_action"] == "PAY_NOW"
    assert (
        context["return_url"]
        == "https://pay.example.test/membership/checkout?order_no=P20260825120000ABC123&plan=yearly"
    )
    assert context["cancel_url"] == context["return_url"]


def test_create_payment_live_mode_uses_live_api_base() -> None:
    api = _PayPalApi()
    _provider(api.transport(), sandbox=False).create_payment(
        order=ORDER, notify_url="https://pay.example.test/cb", return_url=None
    )
    assert all(str(req.url).startswith("https://api-m.paypal.com/") for req in api.requests)


def test_create_payment_missing_approve_link_maps_to_upstream_error() -> None:
    api = _PayPalApi(order_payload={"id": "5O190127TN364715T", "links": [{"rel": "self", "href": "x"}]})
    with pytest.raises(ChannelUpstreamError, match="approve"):
        _provider(api.transport()).create_payment(
            order=ORDER, notify_url="https://pay.example.test/cb", return_url=None
        )


def test_create_payment_rejected_order_maps_to_upstream_error() -> None:
    api = _PayPalApi(order_status=422, order_payload={"name": "UNPROCESSABLE_ENTITY"})
    with pytest.raises(ChannelUpstreamError, match="HTTP 422"):
        _provider(api.transport()).create_payment(
            order=ORDER, notify_url="https://pay.example.test/cb", return_url=None
        )


def test_oauth_failure_maps_to_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid_client"})

    with pytest.raises(ChannelUpstreamError, match="HTTP 401"):
        _provider(httpx.MockTransport(handler)).create_payment(
            order=ORDER, notify_url="https://pay.example.test/cb", return_url=None
        )


# ── 回调：验签 + 事件分派 ────────────────────────────────────────────────


def test_callback_sends_verify_webhook_signature_with_five_headers_and_webhook_id() -> None:
    api = _PayPalApi()
    event = _capture_completed_event()
    verified = _provider(api.transport()).verify_and_parse_callback(
        raw_body=json.dumps(event).encode(), headers=TRANSMISSION_HEADERS
    )

    verify_req = next(
        req for req in api.requests if req.url.path == "/v1/notifications/verify-webhook-signature"
    )
    body = json.loads(verify_req.content)
    assert body["webhook_id"] == WEBHOOK_ID
    assert body["transmission_id"] == "tid-123"
    assert body["transmission_time"] == "2026-08-25T12:00:00Z"
    assert body["transmission_sig"] == "sig-abc"
    assert body["cert_url"] == TRANSMISSION_HEADERS["paypal-cert-url"]
    assert body["auth_algo"] == "SHA256withRSA"
    # 原始事件整体随 webhook_event 上送（验签语义覆盖报文全文）
    assert body["webhook_event"] == event

    assert verified is not None
    assert verified.order_no == ORDER["order_no"]
    # 渠道单号优先 supplementary_data.related_ids.order_id（订单粒度）
    assert verified.channel_order_no == "5O190127TN364715T"
    assert verified.amount_cents == 15900
    assert verified.currency == "USD"
    assert verified.paid_at == datetime(2026, 8, 25, 12, 30, tzinfo=timezone.utc)


def test_callback_rejects_when_verification_status_not_success() -> None:
    api = _PayPalApi(verification_status="FAILURE")
    with pytest.raises(CallbackVerificationError):
        _provider(api.transport()).verify_and_parse_callback(
            raw_body=json.dumps(_capture_completed_event()).encode(), headers=TRANSMISSION_HEADERS
        )


def test_callback_rejects_missing_transmission_headers_without_upstream_call() -> None:
    api = _PayPalApi()
    with pytest.raises(CallbackVerificationError, match="transmission"):
        _provider(api.transport()).verify_and_parse_callback(raw_body=b"{}", headers={})
    # 五头不齐直接拒，不打验签上游
    assert api.requests == []


def test_callback_verify_upstream_failure_maps_to_channel_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok"})
        return httpx.Response(503, text="upstream down")

    with pytest.raises(ChannelUpstreamError, match="HTTP 503"):
        _provider(httpx.MockTransport(handler)).verify_and_parse_callback(
            raw_body=json.dumps(_capture_completed_event()).encode(), headers=TRANSMISSION_HEADERS
        )


def test_order_approved_triggers_server_side_capture_and_returns_none() -> None:
    api = _PayPalApi()
    event = {
        "event_type": "CHECKOUT.ORDER.APPROVED",
        "resource": {
            "id": "5O190127TN364715T",
            "purchase_units": [{"custom_id": ORDER["order_no"], "reference_id": ORDER["order_no"]}],
        },
    }
    result = _provider(api.transport()).verify_and_parse_callback(
        raw_body=json.dumps(event).encode(), headers=TRANSMISSION_HEADERS
    )

    # 验签通过但非终态：None（路由 ACK 200 零状态变更，落账等 CAPTURE.COMPLETED）
    assert result is None
    capture_req = next(req for req in api.requests if req.url.path.endswith("/capture"))
    assert capture_req.method == "POST"
    # capture 幂等头 = order_no + "-capture"
    assert capture_req.headers["PayPal-Request-Id"] == f"{ORDER['order_no']}-capture"


def test_order_approved_capture_failure_raises_for_channel_retry() -> None:
    api = _PayPalApi(capture_status=500)
    event = {"event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": "5O190127TN364715T"}}
    with pytest.raises(ChannelUpstreamError, match="HTTP 500"):
        _provider(api.transport()).verify_and_parse_callback(
            raw_body=json.dumps(event).encode(), headers=TRANSMISSION_HEADERS
        )


def test_unrelated_event_returns_none_after_successful_verification() -> None:
    api = _PayPalApi()
    event = {"event_type": "PAYMENT.CAPTURE.DENIED", "resource": {"id": "CAPTURE-9F1"}}
    assert (
        _provider(api.transport()).verify_and_parse_callback(
            raw_body=json.dumps(event).encode(), headers=TRANSMISSION_HEADERS
        )
        is None
    )


def test_capture_completed_without_custom_id_is_rejected() -> None:
    api = _PayPalApi()
    event = _capture_completed_event()
    del event["resource"]["custom_id"]
    with pytest.raises(CallbackVerificationError, match="custom_id"):
        _provider(api.transport()).verify_and_parse_callback(
            raw_body=json.dumps(event).encode(), headers=TRANSMISSION_HEADERS
        )


def test_capture_completed_falls_back_to_capture_id_as_channel_order_no() -> None:
    api = _PayPalApi()
    event = _capture_completed_event()
    del event["resource"]["supplementary_data"]
    verified = _provider(api.transport()).verify_and_parse_callback(
        raw_body=json.dumps(event).encode(), headers=TRANSMISSION_HEADERS
    )
    assert verified is not None
    assert verified.channel_order_no == "CAPTURE-9F1"


# ── 金额/时间 fail-closed ────────────────────────────────────────────────


def test_amount_helpers_are_fail_closed() -> None:
    assert _amount_value(15900) == "159.00"
    assert _amount_to_cents("9.99") == 999
    assert _amount_to_cents("159.00") == 15900
    for bad in ("abc", "", "0", "-1", "NaN", "Infinity", "1.001"):
        with pytest.raises((CallbackVerificationError, ValueError)):
            _amount_to_cents(bad)
    for bad in (0, -5, "x"):
        with pytest.raises(ValueError):
            _amount_value(bad)


def test_parse_paypal_time_requires_timezone() -> None:
    assert _parse_paypal_time("2026-08-25T12:30:00Z") == datetime(2026, 8, 25, 12, 30, tzinfo=timezone.utc)
    with pytest.raises(CallbackVerificationError):
        _parse_paypal_time("2026-08-25 12:30:00")
    with pytest.raises(CallbackVerificationError):
        _parse_paypal_time(None)


# ── is_configured / ACK / query ──────────────────────────────────────────


def test_unconfigured_capabilities_raise_provider_not_configured() -> None:
    provider = _provider(client_secret="")
    assert provider.is_configured() is False
    with pytest.raises(ProviderNotConfiguredError):
        provider.create_payment(order=ORDER, notify_url="https://x/cb", return_url=None)
    with pytest.raises(ProviderNotConfiguredError):
        provider.verify_and_parse_callback(raw_body=b"{}", headers=TRANSMISSION_HEADERS)
    with pytest.raises(ProviderNotConfiguredError):
        provider.query_order(order=ORDER)
    # 三凭证缺一不可
    assert _provider(webhook_id="").is_configured() is False


def test_ack_contract_is_empty_json_with_status_signal() -> None:
    provider = _provider()
    ok = provider.build_ack_response(ok=True)
    assert ok.status_code == 200
    assert json.loads(bytes(ok.body)) == {}
    assert provider.build_ack_response(ok=False).status_code == 400


def test_query_order_uses_bound_channel_order_no() -> None:
    api = _PayPalApi()
    provider = _provider(api.transport())
    with pytest.raises(ProviderNotConfiguredError, match="channel order no"):
        provider.query_order(order={"order_no": "P1", "channel_order_no": ""})

    status = provider.query_order(order={"order_no": "P1", "channel_order_no": "5O190127TN364715T"})
    assert status == "COMPLETED"
    query_req = api.requests[-1]
    assert query_req.method == "GET"
    assert query_req.url.path == "/v2/checkout/orders/5O190127TN364715T"
