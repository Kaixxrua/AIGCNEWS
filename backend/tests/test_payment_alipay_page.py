"""支付宝电脑网站支付 RSA2、金额归一与 trade.query 契约测试。"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from backend.app.services.payments.providers.alipay_page import (
    _canonical_params,
    AlipayPagePaymentProvider,
)
from backend.app.services.payments.providers.base import (
    CallbackVerificationError,
    ChannelUpstreamError,
)


APP_ID = "2021000000000000"
ORDER = {
    "order_no": "P20260820120000ABC123",
    "plan_code": "member_yearly",
    "amount_cents": 12900,
    "currency": "CNY",
}


@pytest.fixture(scope="module")
def key_pair() -> tuple[rsa.RSAPrivateKey, str, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private, private_pem, public_pem


def _provider(key_pair: tuple[rsa.RSAPrivateKey, str, str]) -> AlipayPagePaymentProvider:
    _, private_pem, public_pem = key_pair
    return AlipayPagePaymentProvider(
        SimpleNamespace(
            alipay_appid=APP_ID,
            alipay_private_key_pem=private_pem,
            alipay_public_key_pem=public_pem,
        )
    )


def _callback_fields() -> dict[str, str]:
    return {
        "app_id": APP_ID,
        "out_trade_no": ORDER["order_no"],
        "trade_no": "2026082022000000000000000001",
        "trade_status": "TRADE_SUCCESS",
        "total_amount": "129.00",
        "gmt_payment": "2026-08-20 20:30:00",
        "sign_type": "RSA2",
    }


def _signed_callback(
    fields: dict[str, str], private: rsa.RSAPrivateKey
) -> tuple[bytes, str]:
    signature = private.sign(
        _canonical_params(fields).encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    encoded = base64.b64encode(signature).decode("ascii")
    with_sign = {**fields, "sign": encoded}
    return str(httpx.QueryParams(with_sign)).encode(), encoded


def test_create_payment_builds_signed_page_pay_redirect(key_pair: tuple) -> None:
    private, _, public_pem = key_pair
    provider = _provider(key_pair)

    instruction = provider.create_payment(
        order=ORDER,
        notify_url="https://pay.example.test/api/payments/callback/alipay_page",
        return_url="https://pay.example.test/membership/checkout",
    )

    parsed = dict(httpx.QueryParams(instruction.content.split("?", 1)[1]))
    assert instruction.kind == "redirect_url"
    assert parsed["app_id"] == APP_ID
    assert parsed["method"] == "alipay.trade.page.pay"
    assert parsed["sign_type"] == "RSA2"
    assert parsed["notify_url"].endswith("/api/payments/callback/alipay_page")
    assert parsed["return_url"].endswith("order_no=P20260820120000ABC123&plan=yearly")
    biz_content = json.loads(parsed["biz_content"])
    assert biz_content == {
        "out_trade_no": ORDER["order_no"],
        "total_amount": "129.00",
        "subject": "AIGC Radar Membership (Yearly)",
        "product_code": "FAST_INSTANT_TRADE_PAY",
    }
    public = serialization.load_pem_public_key(public_pem.encode())
    public.verify(
        base64.b64decode(parsed["sign"]),
        _canonical_params({key: value for key, value in parsed.items() if key != "sign"}).encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_callback_rsa2_round_trip_normalizes_yuan_to_cents(
    key_pair: tuple[rsa.RSAPrivateKey, str, str],
) -> None:
    private, _, _ = key_pair
    fields = _callback_fields()
    body, _ = _signed_callback(fields, private)

    verified = _provider(key_pair).verify_and_parse_callback(raw_body=body, headers={})

    assert verified.order_no == ORDER["order_no"]
    assert verified.channel_order_no == "2026082022000000000000000001"
    assert verified.amount_cents == 12900
    assert verified.currency == "CNY"
    assert verified.paid_at == datetime(2026, 8, 20, 12, 30, tzinfo=timezone.utc)


def test_callback_rejects_three_decimal_amount_bad_signature_and_unsuccessful_status(
    key_pair: tuple[rsa.RSAPrivateKey, str, str],
) -> None:
    private, _, _ = key_pair
    fields = _callback_fields()
    fields["total_amount"] = "129.001"
    body, _ = _signed_callback(fields, private)
    with pytest.raises(CallbackVerificationError, match="at most two decimals"):
        _provider(key_pair).verify_and_parse_callback(raw_body=body, headers={})

    fields = _callback_fields()
    body, _ = _signed_callback(fields, private)
    tampered = body.replace(b"TRADE_SUCCESS", b"TRADE_FINISHED")
    # Tampering the raw form invalidates RSA2 before business status handling.
    with pytest.raises(CallbackVerificationError, match="signature mismatch"):
        _provider(key_pair).verify_and_parse_callback(raw_body=tampered, headers={})

    fields["trade_status"] = "WAIT_BUYER_PAY"
    body, _ = _signed_callback(fields, private)
    with pytest.raises(CallbackVerificationError, match="not successful"):
        _provider(key_pair).verify_and_parse_callback(raw_body=body, headers={})


def test_query_order_posts_signed_trade_query_and_returns_status(
    key_pair: tuple[rsa.RSAPrivateKey, str, str],
) -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json={"alipay_trade_query_response": {"trade_status": "TRADE_SUCCESS"}},
        )

    private, private_pem, public_pem = key_pair
    provider = AlipayPagePaymentProvider(
        SimpleNamespace(
            alipay_appid=APP_ID,
            alipay_private_key_pem=private_pem,
            alipay_public_key_pem=public_pem,
        ),
        transport=httpx.MockTransport(handler),
    )
    assert provider.query_order(order=ORDER) == "TRADE_SUCCESS"

    request = captured["request"]
    assert request.method == "POST"
    assert str(request.url) == "https://openapi.alipay.com/gateway.do"
    form = dict(httpx.QueryParams(request.content.decode()))
    assert form["method"] == "alipay.trade.query"
    assert json.loads(form["biz_content"]) == {"out_trade_no": ORDER["order_no"]}
    public = serialization.load_pem_public_key(public_pem.encode())
    public.verify(
        base64.b64decode(form["sign"]),
        _canonical_params({key: value for key, value in form.items() if key != "sign"}).encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_query_order_maps_upstream_500() -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    provider = AlipayPagePaymentProvider(
        SimpleNamespace(
            alipay_appid=APP_ID,
            alipay_private_key_pem=private_pem,
            alipay_public_key_pem=public_pem,
        ),
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )
    with pytest.raises(ChannelUpstreamError, match="HTTP 500"):
        provider.query_order(order=ORDER)
