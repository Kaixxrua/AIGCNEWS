"""ShinyDesk 测试替身：有状态的 PayPal v2 上游与授权服务器 purchases 接口。

FakePayPal 驱动真实 PayPalProvider（httpx.MockTransport），webhook 验签只认
genuine() 登记过的 transmission id，其余一律 FAILURE（模拟伪造通知）。
FakeLicenseApi 按授权服务器 purchases.cjs 的协议校验 HMAC、时间窗与 nonce，
以 PayPal 订单号幂等发码。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from types import SimpleNamespace
from typing import Any

import httpx

from backend.app.services.payments.providers.paypal import PayPalProvider

LICENSE_KEY = b"test-only-license-hmac-key-0123456789abcdef"
LICENSE_KEY_ID = "aigcnews-test"
LICENSE_BASE = "https://license.test/shiny-service"


class FakePayPal:
    def __init__(self) -> None:
        self.orders: dict[str, dict[str, Any]] = {}
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []
        self.genuine_ids: set[str] = set()
        self.capture_override: dict[str, dict[str, str]] = {}
        self.capture_status = "COMPLETED"

    def provider(self) -> PayPalProvider:
        return PayPalProvider(
            SimpleNamespace(
                overseas_provider="paypal",
                overseas_sandbox=True,
                overseas_client_id="cid",
                overseas_client_secret="secret",
                overseas_webhook_secret="WH-1",
            ),
            transport=httpx.MockTransport(self._handle),
        )

    # 买家在 PayPal 页面点了「付款」
    def approve(self, paypal_order_id: str, email: str = "Buyer@Example.com") -> None:
        order = self.orders[paypal_order_id]
        order["status"] = "APPROVED"
        order["payer_email"] = email

    def genuine(self) -> dict[str, str]:
        transmission_id = secrets.token_hex(8)
        self.genuine_ids.add(transmission_id)
        return {
            "paypal-transmission-id": transmission_id,
            "paypal-transmission-time": "2026-10-30T10:00:00Z",
            "paypal-transmission-sig": "sig",
            "paypal-cert-url": "https://api-m.sandbox.paypal.com/cert.pem",
            "paypal-auth-algo": "SHA256withRSA",
            "content-type": "application/json",
        }

    def forged(self) -> dict[str, str]:
        headers = self.genuine()
        self.genuine_ids.discard(headers["paypal-transmission-id"])
        return headers

    def representation(self, paypal_order_id: str) -> dict[str, Any]:
        order = self.orders[paypal_order_id]
        unit: dict[str, Any] = {"reference_id": order["custom_id"], "custom_id": order["custom_id"], "amount": order["amount"]}
        if order.get("capture_id"):
            unit["payments"] = {
                "captures": [
                    {
                        "id": order["capture_id"],
                        "status": order["capture_status"],
                        "amount": order["captured_amount"],
                        "custom_id": order["custom_id"],
                        "create_time": "2026-10-30T10:00:05Z",
                    }
                ]
            }
        payload = {"id": paypal_order_id, "status": order["status"], "purchase_units": [unit]}
        if order.get("payer_email"):
            payload["payer"] = {"email_address": order["payer_email"]}
        return payload

    def _issue(self, status: int, issue: str) -> httpx.Response:
        return httpx.Response(status, json={"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": issue}]})

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content and request.method == "POST" and path != "/v1/oauth2/token" else None
        self.requests.append((request.method, path, body))
        if path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "tok"})
        if path == "/v2/checkout/orders" and request.method == "POST":
            paypal_order_id = "PP" + secrets.token_hex(8).upper()[:15]
            unit = body["purchase_units"][0]
            self.orders[paypal_order_id] = {
                "status": "CREATED",
                "custom_id": unit["custom_id"],
                "amount": unit["amount"],
                "request": body,
            }
            return httpx.Response(
                201,
                json={
                    "id": paypal_order_id,
                    "status": "CREATED",
                    "links": [{"rel": "approve", "href": f"https://www.sandbox.paypal.com/checkoutnow?token={paypal_order_id}"}],
                },
            )
        if path == "/v1/notifications/verify-webhook-signature":
            ok = body["transmission_id"] in self.genuine_ids and body["webhook_id"] == "WH-1"
            return httpx.Response(200, json={"verification_status": "SUCCESS" if ok else "FAILURE"})
        if path.startswith("/v2/checkout/orders/"):
            parts = path.split("/")
            paypal_order_id = parts[4]
            order = self.orders.get(paypal_order_id)
            if order is None:
                return httpx.Response(404, json={"name": "RESOURCE_NOT_FOUND"})
            if path.endswith("/capture"):
                if order["status"] == "COMPLETED":
                    return self._issue(422, "ORDER_ALREADY_CAPTURED")
                if order["status"] != "APPROVED":
                    return self._issue(422, "ORDER_NOT_APPROVED")
                order["status"] = "COMPLETED"
                order["capture_id"] = "CAP" + secrets.token_hex(8).upper()[:14]
                order["capture_status"] = self.capture_status
                order["captured_amount"] = self.capture_override.get(paypal_order_id, order["amount"])
                return httpx.Response(201, json=self.representation(paypal_order_id))
            return httpx.Response(200, json=self.representation(paypal_order_id))
        raise AssertionError(f"unexpected paypal path {request.method} {path}")

    # ── webhook 报文 ──
    def approved_event(self, paypal_order_id: str) -> dict[str, Any]:
        order = self.orders[paypal_order_id]
        return {
            "event_type": "CHECKOUT.ORDER.APPROVED",
            "resource": {"id": paypal_order_id, "purchase_units": [{"custom_id": order["custom_id"], "reference_id": order["custom_id"]}]},
        }

    def completed_event(self, paypal_order_id: str) -> dict[str, Any]:
        order = self.orders[paypal_order_id]
        return {
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "create_time": "2026-10-30T10:00:06Z",
            "resource": {
                "id": order["capture_id"],
                "status": "COMPLETED",
                "custom_id": order["custom_id"],
                "amount": order["captured_amount"],
                "create_time": "2026-10-30T10:00:05Z",
                "supplementary_data": {"related_ids": {"order_id": paypal_order_id}},
            },
        }

    def refunded_event(self, paypal_order_id: str, event_type: str = "PAYMENT.CAPTURE.REFUNDED") -> dict[str, Any]:
        capture_id = self.orders[paypal_order_id]["capture_id"]
        return {
            "event_type": event_type,
            "resource": {
                "id": "REF" + secrets.token_hex(6).upper(),
                "status": "COMPLETED",
                "amount": {"value": "9.99", "currency_code": "USD"},
                "links": [{"rel": "up", "href": f"https://api.sandbox.paypal.com/v2/payments/captures/{capture_id}"}],
            },
        }

    def dispute_event(self, paypal_order_id: str, event_type: str = "CUSTOMER.DISPUTE.CREATED") -> dict[str, Any]:
        capture_id = self.orders[paypal_order_id]["capture_id"]
        return {
            "event_type": event_type,
            "resource": {"dispute_id": "PP-D-1", "status": "OPEN", "disputed_transactions": [{"seller_transaction_id": capture_id}]},
        }


class FakeLicenseApi:
    """授权服务器 /v1/internal/purchases/* 的协议替身（HMAC + 时间窗 + nonce + 幂等）。"""

    def __init__(self) -> None:
        self.purchases: dict[str, dict[str, Any]] = {}
        self.nonces: set[str] = set()
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.down = False

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("license service down", request=request)
        assert request.url.path.startswith("/shiny-service/")
        route = request.url.path[len("/shiny-service"):]
        timestamp = request.headers.get("x-purchase-timestamp", "")
        nonce = request.headers.get("x-purchase-nonce", "")
        message = "\n".join(
            ["SHINY-PURCHASE-V1", "POST", route, timestamp, nonce, hashlib.sha256(request.content).hexdigest()]
        )
        expected = hmac.new(LICENSE_KEY, message.encode(), hashlib.sha256).hexdigest()
        if (
            request.headers.get("x-purchase-key") != LICENSE_KEY_ID
            or not hmac.compare_digest(expected, request.headers.get("x-purchase-signature", ""))
            or abs(time.time() * 1000 - int(timestamp or 0)) > 300000
        ):
            return httpx.Response(401, json={"ok": False, "error": "Unauthorized"})
        if nonce in self.nonces:
            return httpx.Response(409, json={"ok": False, "error": "Replayed request"})
        self.nonces.add(nonce)
        body = json.loads(request.content)
        action = route.rsplit("/", 1)[1]
        self.calls.append((action, body))
        order_id = body.get("orderId")
        if action == "issue":
            assert (body["product"], body["amountCents"], body["currency"]) == ("shinydesk-standard", 999, "USD")
            record = self.purchases.get(order_id)
            replayed = record is not None
            if record is None:
                record = {"orderId": order_id, "orderNo": body["orderNo"], "licenseId": "lic-" + secrets.token_hex(4),
                          "code": "PB-" + secrets.token_hex(20).upper(), "revoked": False}
                self.purchases[order_id] = record
            return httpx.Response(200, json={"ok": True, "result": {**record, "replayed": replayed}})
        record = self.purchases.get(order_id)
        if record is None:
            return httpx.Response(404, json={"ok": False, "error": "Unknown order"})
        if action == "revoke":
            record["revoked"] = True
            record.setdefault("revokeReason", body["reason"])
        return httpx.Response(200, json={"ok": True, "result": dict(record)})

    @property
    def issued(self) -> int:
        return sum(1 for action, _ in self.calls if action == "issue")
