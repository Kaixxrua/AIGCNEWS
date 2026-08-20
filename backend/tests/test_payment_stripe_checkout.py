"""Stripe Checkout 真实下单与 webhook 验签契约测试。"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import (
    get_payment_order_repository,
    get_payment_providers,
)
from backend.app.api.routes_payments import router
from backend.app.core.auth import RequireUser
from backend.app.core.config import settings
from backend.app.services.payments.providers.base import ChannelUpstreamError
from backend.app.services.payments.providers.stripe import StripePaymentProvider


SECRET_KEY = "sk_test_checkout_secret"
WEBHOOK_SECRET = "whsec_checkout_secret"
ORDER = {
    "order_no": "P20260820120000ABC123",
    "plan_code": "member_yearly",
    "amount_cents": 12900,
    "currency": "CNY",
}


def _provider(transport: httpx.BaseTransport | None = None) -> StripePaymentProvider:
    return StripePaymentProvider(
        SimpleNamespace(
            stripe_secret_key=SECRET_KEY,
            stripe_webhook_secret=WEBHOOK_SECRET,
        ),
        transport=transport,
    )


def _event(*, order: dict = ORDER, event_type: str = "checkout.session.completed") -> bytes:
    return json.dumps(
        {
            "id": "evt_test_123",
            "type": event_type,
            "created": 1_755_681_600,
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "payment_intent": "pi_test_123",
                    "amount_total": order["amount_cents"],
                    "currency": order["currency"].lower(),
                    "metadata": {"order_no": order["order_no"]},
                }
            },
        },
        separators=(",", ":"),
    ).encode()


def _signed_headers(body: bytes, *, timestamp: int = 1_755_681_600) -> dict[str, str]:
    digest = hmac.new(
        WEBHOOK_SECRET.encode(),
        f"{timestamp}.".encode() + body,
        hashlib.sha256,
    ).hexdigest()
    return {"Stripe-Signature": f"t={timestamp},v1={digest}"}


def test_create_payment_posts_checkout_form_and_returns_redirect() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json={"id": "cs_test_123", "url": "https://checkout.stripe.test/cs_test_123"},
        )

    instruction = _provider(httpx.MockTransport(handler)).create_payment(
        order=ORDER,
        notify_url="https://pay.example.test/api/payments/callback/stripe",
        return_url="https://pay.example.test/membership/checkout",
    )

    request = captured["request"]
    assert isinstance(request, httpx.Request)
    assert request.method == "POST"
    assert str(request.url) == "https://api.stripe.com/v1/checkout/sessions"
    assert request.headers["Authorization"] == f"Bearer {SECRET_KEY}"
    form = dict(httpx.QueryParams(request.content.decode()))
    assert form == {
        "mode": "payment",
        "line_items[0][price_data][currency]": "cny",
        "line_items[0][price_data][unit_amount]": "12900",
        "line_items[0][price_data][product_data][name]": "AIGC Radar Membership (Yearly)",
        "line_items[0][quantity]": "1",
        "metadata[order_no]": ORDER["order_no"],
        "client_reference_id": ORDER["order_no"],
        "success_url": "https://pay.example.test/membership/checkout?order_no=P20260820120000ABC123&plan=yearly",
        "cancel_url": "https://pay.example.test/membership/checkout?order_no=P20260820120000ABC123&plan=yearly",
    }
    assert instruction.kind == "redirect_url"
    assert instruction.content == "https://checkout.stripe.test/cs_test_123"


def test_create_payment_maps_network_failure_to_channel_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "upstream down"}})

    with pytest.raises(ChannelUpstreamError, match="HTTP 500"):
        _provider(httpx.MockTransport(handler)).create_payment(
            order=ORDER,
            notify_url="https://pay.example.test/callback",
            return_url=None,
        )


def test_webhook_signature_round_trip_parses_cents_and_uppercases_currency() -> None:
    body = _event()
    with patch("backend.app.services.payments.providers.stripe.time.time", return_value=1_755_681_600):
        verified = _provider().verify_and_parse_callback(
            raw_body=body,
            headers=_signed_headers(body),
        )

    assert verified.order_no == ORDER["order_no"]
    assert verified.channel_order_no == "pi_test_123"
    assert verified.amount_cents == 12900
    assert verified.currency == "CNY"
    assert verified.paid_at == datetime.fromtimestamp(1_755_681_600, tz=timezone.utc)


def test_webhook_rejects_expired_timestamp_and_bad_signature() -> None:
    body = _event()
    provider = _provider()
    with patch("backend.app.services.payments.providers.stripe.time.time", return_value=1_755_681_600 + 301):
        with pytest.raises(Exception, match="outside tolerance"):
            provider.verify_and_parse_callback(
                raw_body=body,
                headers=_signed_headers(body),
            )

    bad_headers = {"Stripe-Signature": "t=1755681600,v1=not-the-signature"}
    with patch("backend.app.services.payments.providers.stripe.time.time", return_value=1_755_681_600):
        with pytest.raises(Exception, match="signature mismatch"):
            provider.verify_and_parse_callback(raw_body=body, headers=bad_headers)


def test_webhook_rejects_unsupported_event() -> None:
    body = _event(event_type="payment_intent.succeeded")
    with patch("backend.app.services.payments.providers.stripe.time.time", return_value=1_755_681_600):
        with pytest.raises(Exception, match="unsupported stripe event type"):
            _provider().verify_and_parse_callback(
                raw_body=body,
                headers=_signed_headers(body),
            )


class _Orders:
    def create_order(self, **kwargs: object) -> dict[str, object]:
        return {
            "id": 1,
            **kwargs,
            "status": "pending",
            "channel_order_no": "",
            "paid_at": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }

    def get_order_by_user_and_idempotency_key(self, **kwargs: object) -> None:
        return None


class _FailingProvider:
    channel = "stripe"

    def is_configured(self) -> bool:
        return True

    def create_payment(self, **kwargs: object) -> object:
        raise ChannelUpstreamError("stripe unavailable")


def test_create_order_maps_channel_upstream_failure_to_502(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "payments_enabled", True)
    monkeypatch.setattr(settings, "payments_public_base_url", "https://pay.example.test")
    monkeypatch.setattr(settings, "payments_order_ttl_minutes", 30)
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[RequireUser] = lambda: {"user_id": 7, "role": "user"}
    app.dependency_overrides[get_payment_order_repository] = _Orders
    app.dependency_overrides[get_payment_providers] = lambda: {"stripe": _FailingProvider()}

    response = TestClient(app).post(
        "/api/payments/orders",
        json={"plan_code": "member_monthly", "channel": "stripe"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "payment_channel_upstream_error"
