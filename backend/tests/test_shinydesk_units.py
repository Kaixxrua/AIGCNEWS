"""ShinyDesk 单元契约：HMAC 签名与授权服务器（Node purchases.cjs）逐字节一致、
发码客户端错误映射、PayPal 渠道的增量能力（订单覆盖键、验签/解析拆分、capture 回退）。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from backend.app.services.payments.providers.base import CallbackVerificationError
from backend.app.services.payments.providers.paypal import PayPalOrderNotCapturable, PayPalProvider
from backend.app.services.shinydesk import checkout
from backend.app.services.shinydesk.license_client import (
    LicenseServiceError,
    LicenseServiceRejected,
    ShinyDeskLicenseClient,
    build_license_client,
    signature,
)
from backend.app.services.shinydesk.product import generate_order_no, is_shinydesk_order_no, load_config
from backend.tests.shinydesk_fakes import LICENSE_BASE, LICENSE_KEY, LICENSE_KEY_ID, FakeLicenseApi, FakePayPal

# 由 service082-paypal-r1/service/purchases.cjs 的 sign() 生成（见 NOTES.md 测试一节）
NODE_VECTOR_BODY = b'{"orderId":"5O190127TN364715T","orderNo":"SD20261030120000A1B2C3D4","product":"shinydesk-standard","amountCents":999,"currency":"USD"}'
NODE_VECTOR_SIGNATURE = "a244425086b917b2af980b8eab1d935d853fecfe57139a7cac4ee141f08ec19c"


def test_hmac_signature_matches_node_service_vector() -> None:
    assert (
        signature(
            LICENSE_KEY,
            path="/v1/internal/purchases/issue",
            timestamp="1790000000000",
            nonce="nonce-nonce-nonce-nonce-1",
            body=NODE_VECTOR_BODY,
        )
        == NODE_VECTOR_SIGNATURE
    )


def test_order_numbers_match_license_service_pattern() -> None:
    order_no = generate_order_no()
    assert is_shinydesk_order_no(order_no) and len(order_no) == 24
    assert not is_shinydesk_order_no("P20261030120000ABC123")
    assert not is_shinydesk_order_no("sd20261030120000abcdef12")


def test_config_defaults_off_and_requires_key_file(tmp_path) -> None:
    assert load_config({}).enabled is False
    config = load_config({"SHINYDESK_CHECKOUT_ENABLED": "true", "SHINYDESK_LICENSE_API_BASE": "https://x/shiny-service/"})
    assert config.enabled and config.license_api_base == "https://x/shiny-service"
    assert build_license_client(config) is None  # 无密钥文件
    short = tmp_path / "short"
    short.write_text("short")
    assert build_license_client(load_config({"SHINYDESK_LICENSE_API_BASE": "https://x", "SHINYDESK_LICENSE_HMAC_KEY_FILE": str(short)})) is None
    good = tmp_path / "good"
    good.write_text(LICENSE_KEY.decode() + "\n")
    assert build_license_client(load_config({"SHINYDESK_LICENSE_API_BASE": "https://x", "SHINYDESK_LICENSE_HMAC_KEY_FILE": str(good)})) is not None


def test_license_client_issue_is_idempotent_and_rejects_wrong_key() -> None:
    api = FakeLicenseApi()
    client = ShinyDeskLicenseClient(base_url=LICENSE_BASE, key_id=LICENSE_KEY_ID, secret=LICENSE_KEY, transport=api.transport())
    first = client.issue(paypal_order_id="5O190127TN364715T", order_no="SD20261030120000A1B2C3D4")
    second = client.issue(paypal_order_id="5O190127TN364715T", order_no="SD20261030120000A1B2C3D4")
    assert first.code == second.code and second.replayed and not first.replayed
    forged = ShinyDeskLicenseClient(base_url=LICENSE_BASE, key_id=LICENSE_KEY_ID, secret=b"x" * 40, transport=api.transport())
    with pytest.raises(LicenseServiceRejected) as excinfo:
        forged.issue(paypal_order_id="7XK11111AA2222222", order_no="SD20261030120000A1B2C3D5")
    assert excinfo.value.status_code == 401
    api.down = True
    with pytest.raises(LicenseServiceError):
        client.issue(paypal_order_id="5O190127TN364715T", order_no="SD20261030120000A1B2C3D4")


def test_license_client_rejects_response_for_another_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {"orderId": "OTHER000000000000", "orderNo": "SD20261030120000A1B2C3D4", "code": "PB-" + "A" * 40, "licenseId": "x"}})

    client = ShinyDeskLicenseClient(base_url=LICENSE_BASE, key_id=LICENSE_KEY_ID, secret=LICENSE_KEY, transport=httpx.MockTransport(handler))
    with pytest.raises(LicenseServiceError):
        client.issue(paypal_order_id="5O190127TN364715T", order_no="SD20261030120000A1B2C3D4")


def test_capture_facts_parsing_is_fail_closed() -> None:
    paypal = FakePayPal()
    provider = paypal.provider()
    created = provider.create_payment(
        order={"order_no": "SD20261030120000A1B2C3D4", "plan_code": "shinydesk_standard_usd", "amount_cents": 999, "currency": "USD"},
        notify_url="https://n",
        return_url=None,
    )
    paypal_order_id = created.content.rsplit("token=", 1)[1]
    facts = checkout.capture_facts(paypal.representation(paypal_order_id))
    assert facts.capture_status == "ORDER_CREATED" and facts.capture_id == ""
    paypal.approve(paypal_order_id, "a@b.c")
    facts = checkout.capture_facts(provider.capture_order_details(paypal_order_id=paypal_order_id, request_id="SD1"))
    assert (facts.amount_cents, facts.currency, facts.payer_email, facts.capture_status) == (999, "USD", "a@b.c", "COMPLETED")
    bad = paypal.representation(paypal_order_id)
    bad["purchase_units"][0]["payments"]["captures"][0]["amount"]["value"] = "9.999"
    with pytest.raises(CallbackVerificationError):
        checkout.capture_facts(bad)
    two_units = paypal.representation(paypal_order_id)
    two_units["purchase_units"].append(two_units["purchase_units"][0])
    with pytest.raises(CallbackVerificationError):
        checkout.capture_facts(two_units)
    drift = paypal.representation(paypal_order_id)
    drift["purchase_units"][0]["payments"]["captures"][0]["custom_id"] = "SD20261030120000FFFFFFFF"
    with pytest.raises(CallbackVerificationError):
        checkout.capture_facts(drift)


def test_paypal_capture_falls_back_when_already_captured_and_reports_not_approved() -> None:
    paypal = FakePayPal()
    provider = paypal.provider()
    created = provider.create_payment(
        order={"order_no": "SD20261030120000A1B2C3D4", "plan_code": "x", "amount_cents": 999, "currency": "USD"},
        notify_url="https://n",
        return_url=None,
    )
    paypal_order_id = created.content.rsplit("token=", 1)[1]
    with pytest.raises(PayPalOrderNotCapturable) as excinfo:
        provider.capture_order_details(paypal_order_id=paypal_order_id, request_id="SD1")
    assert excinfo.value.issue == "ORDER_NOT_APPROVED"
    paypal.approve(paypal_order_id)
    first = provider.capture_order_details(paypal_order_id=paypal_order_id, request_id="SD1")
    second = provider.capture_order_details(paypal_order_id=paypal_order_id, request_id="SD1")  # 422 ALREADY_CAPTURED → GET
    assert first["purchase_units"][0]["payments"] == second["purchase_units"][0]["payments"]
    capture_headers = [r for r in paypal.requests if r[1].endswith("/capture")]
    assert len(capture_headers) == 3


def test_verify_and_parse_split_is_equivalent_to_original_method() -> None:
    paypal = FakePayPal()
    provider = paypal.provider()
    event = {
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": "CAP1",
            "custom_id": "P20260825120000ABC123",
            "amount": {"value": "39.00", "currency_code": "USD"},
            "create_time": "2026-08-25T12:30:00Z",
            "supplementary_data": {"related_ids": {"order_id": "ORDER1"}},
        },
    }
    raw = json.dumps(event).encode()
    combined = provider.verify_and_parse_callback(raw_body=raw, headers=paypal.genuine())
    split = provider.parse_verified_event(provider.verify_webhook_event(raw_body=raw, headers=paypal.genuine()))
    assert combined == split and combined.amount_cents == 3900
    with pytest.raises(CallbackVerificationError):
        provider.verify_webhook_event(raw_body=raw, headers=paypal.forged())


def test_membership_order_payload_is_unchanged_by_override_keys() -> None:
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t"})
        sent.append(json.loads(request.content))
        return httpx.Response(201, json={"links": [{"rel": "approve", "href": "https://p/?token=X"}]})

    provider = PayPalProvider(
        SimpleNamespace(overseas_provider="paypal", overseas_sandbox=True, overseas_client_id="a", overseas_client_secret="b", overseas_webhook_secret="c"),
        transport=httpx.MockTransport(handler),
    )
    provider.create_payment(
        order={"order_no": "P1", "plan_code": "member_yearly", "amount_cents": 3900, "currency": "USD"},
        notify_url="https://n",
        return_url="https://site/membership/checkout",
    )
    body = sent[0]
    assert body["purchase_units"][0]["description"] == "AIGC Radar Membership (Yearly)"
    assert body["application_context"] == {
        "brand_name": "AIGC Radar",
        "user_action": "PAY_NOW",
        "return_url": "https://site/membership/checkout?order_no=P1&plan=yearly",
        "cancel_url": "https://site/membership/checkout?order_no=P1&plan=yearly",
    }
