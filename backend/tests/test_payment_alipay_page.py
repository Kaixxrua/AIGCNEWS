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
    "amount_cents": 15900,
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
        "total_amount": "159.00",
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
        "total_amount": "159.00",
        "subject": "AIGC Radar Membership (Yearly)",
        "product_code": "FAST_INSTANT_TRADE_PAY",
    }
    public = serialization.load_pem_public_key(public_pem.encode())
    public.verify(
        base64.b64decode(parsed["sign"]),
        _canonical_params(
            {key: value for key, value in parsed.items() if key != "sign"},
            exclude_sign_type=False,
        ).encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_request_sign_string_includes_sign_type() -> None:
    """钉死请求加签串形状：与网关 invalid-signature 报错里的验签串同构。

    网关原文（2026-08-22 真实报错）：app_id=...&biz_content={...}&charset=utf-8
    &method=alipay.trade.page.pay&notify_url=...&return_url=...&sign_type=RSA2
    &timestamp=...&version=1.0 —— sign_type 必须参与请求签名。
    """
    params = {
        "app_id": APP_ID,
        "method": "alipay.trade.page.pay",
        "charset": "utf-8",
        "sign_type": "RSA2",
        "timestamp": "2026-08-22 09:00:43",
        "version": "1.0",
        "notify_url": "https://aigcnews.cn/api/payments/callback/alipay_page",
        "return_url": "https://aigcnews.cn/membership/checkout?order_no=P20260822090043729004&plan=monthly",
        "biz_content": '{"out_trade_no":"P20260822090043729004","total_amount":"19.00","subject":"AIGC Radar Membership (Monthly)","product_code":"FAST_INSTANT_TRADE_PAY"}',
    }
    assert _canonical_params(params, exclude_sign_type=False) == (
        'app_id=2021000000000000&biz_content={"out_trade_no":"P20260822090043729004",'
        '"total_amount":"19.00","subject":"AIGC Radar Membership (Monthly)",'
        '"product_code":"FAST_INSTANT_TRADE_PAY"}&charset=utf-8&method=alipay.trade.page.pay'
        "&notify_url=https://aigcnews.cn/api/payments/callback/alipay_page"
        "&return_url=https://aigcnews.cn/membership/checkout?order_no=P20260822090043729004&plan=monthly"
        "&sign_type=RSA2&timestamp=2026-08-22 09:00:43&version=1.0"
    )
    # 回调验签仍按官方规则剔除 sign_type
    assert "sign_type" not in _canonical_params(params)


def test_callback_rsa2_round_trip_normalizes_yuan_to_cents(
    key_pair: tuple[rsa.RSAPrivateKey, str, str],
) -> None:
    private, _, _ = key_pair
    fields = _callback_fields()
    body, _ = _signed_callback(fields, private)

    verified = _provider(key_pair).verify_and_parse_callback(raw_body=body, headers={})

    assert verified.order_no == ORDER["order_no"]
    assert verified.channel_order_no == "2026082022000000000000000001"
    assert verified.amount_cents == 15900
    assert verified.currency == "CNY"
    assert verified.paid_at == datetime(2026, 8, 20, 12, 30, tzinfo=timezone.utc)


def test_callback_rejects_three_decimal_amount_bad_signature_and_unsuccessful_status(
    key_pair: tuple[rsa.RSAPrivateKey, str, str],
) -> None:
    private, _, _ = key_pair
    fields = _callback_fields()
    fields["total_amount"] = "159.001"
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
        _canonical_params(
            {key: value for key, value in form.items() if key != "sign"},
            exclude_sign_type=False,
        ).encode(),
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


def _bare_base64(pem: str) -> str:
    """模拟支付宝密钥工具导出形态：剥掉 PEM 头尾，只留 Base64 主体。"""
    return "".join(line for line in pem.splitlines() if not line.startswith("-----"))


def test_bare_base64_keys_sign_and_verify_round_trip(
    key_pair: tuple[rsa.RSAPrivateKey, str, str],
) -> None:
    """monitor 面板粘入的常为无头尾裸 Base64，必须与 PEM 文本等效可用。"""
    private, private_pem, public_pem = key_pair
    provider = AlipayPagePaymentProvider(
        SimpleNamespace(
            alipay_appid=APP_ID,
            alipay_private_key_pem=_bare_base64(private_pem),
            alipay_public_key_pem=_bare_base64(public_pem),
        )
    )
    assert provider.is_configured()

    instruction = provider.create_payment(
        order=ORDER,
        notify_url="https://pay.example.test/api/payments/callback/alipay_page",
        return_url=None,
    )
    parsed = dict(httpx.QueryParams(instruction.content.split("?", 1)[1]))
    public = serialization.load_pem_public_key(public_pem.encode())
    public.verify(
        base64.b64decode(parsed["sign"]),
        _canonical_params(
            {key: value for key, value in parsed.items() if key != "sign"},
            exclude_sign_type=False,
        ).encode(),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )

    body, _ = _signed_callback(_callback_fields(), private)
    verified = provider.verify_and_parse_callback(raw_body=body, headers={})
    assert verified.order_no == ORDER["order_no"]


def test_bare_base64_tolerates_embedded_whitespace_and_pkcs1(
    key_pair: tuple[rsa.RSAPrivateKey, str, str],
) -> None:
    private, private_pem, public_pem = key_pair
    # 编辑器复制常带入的 64 列折行
    folded_private = "\n".join(
        _bare_base64(private_pem)[i : i + 64]
        for i in range(0, len(_bare_base64(private_pem)), 64)
    )
    # PKCS#1（TraditionalOpenSSL）裸 Base64 也须可加载
    pkcs1_bare = _bare_base64(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ).decode()
    )
    for candidate in (folded_private, pkcs1_bare):
        provider = AlipayPagePaymentProvider(
            SimpleNamespace(
                alipay_appid=APP_ID,
                alipay_private_key_pem=candidate,
                alipay_public_key_pem=public_pem,
            )
        )
        instruction = provider.create_payment(
            order=ORDER,
            notify_url="https://pay.example.test/api/payments/callback/alipay_page",
            return_url=None,
        )
        assert instruction.kind == "redirect_url"


def test_pem_file_path_still_supported(
    key_pair: tuple[rsa.RSAPrivateKey, str, str], tmp_path
) -> None:
    """env 形态的文件路径输入不得被裸 Base64 兼容破坏。"""
    private, private_pem, public_pem = key_pair
    private_path = tmp_path / "alipay_private.pem"
    public_path = tmp_path / "alipay_public.pem"
    private_path.write_text(private_pem)
    public_path.write_text(public_pem)
    provider = AlipayPagePaymentProvider(
        SimpleNamespace(
            alipay_appid=APP_ID,
            alipay_private_key_pem=str(private_path),
            alipay_public_key_pem=str(public_path),
        )
    )
    body, _ = _signed_callback(_callback_fields(), private)
    verified = provider.verify_and_parse_callback(raw_body=body, headers={})
    assert verified.order_no == ORDER["order_no"]
