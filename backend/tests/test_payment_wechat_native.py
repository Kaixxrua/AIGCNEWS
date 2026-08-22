"""微信支付 Native 下单签名、回调验签（公钥模式 + AES-GCM）与查单契约测试。

纪律提醒（与支付宝 golden-string 测试同一教训）：本文件的"微信侧"密钥
（支付公钥密钥对）与商户密钥对都是测试自制——round-trip 只能证明自洽，
签名串/Auth 头/加密信封的形状按官方 v3 文档逐字段钉死，才是与真实网关
对接的契约。
"""

from __future__ import annotations

import base64
import json
import re
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from backend.app.services.payments.providers.base import (
    CallbackVerificationError,
    ChannelUpstreamError,
    ProviderNotConfiguredError,
)
from backend.app.services.payments.providers.wechat_native import (
    WeChatNativePaymentProvider,
)

APPID = "wxd678efh567hg6787"
MCHID = "1900000109"
SERIAL_NO = "5157F09EFDC096DE15EBE81A47057A72"
API_V3_KEY = "k" * 32
PAY_PUBLIC_KEY_ID = "PUB_KEY_ID_0114000000000000000000000000"
ORDER = {
    "order_no": "P20260822120000ABC123",
    "plan_code": "member_yearly",
    "amount_cents": 15900,
    "currency": "CNY",
}
NOTIFY_URL = "https://aigcnews.cn/api/payments/callback/wechat_native"

_AUTH_RE = re.compile(
    r'^WECHATPAY2-SHA256-RSA2048 mchid="(?P<mchid>[^"]+)",nonce_str="(?P<nonce>[^"]+)",'
    r'signature="(?P<signature>[^"]+)",timestamp="(?P<timestamp>[^"]+)",'
    r'serial_no="(?P<serial>[^"]+)"$'
)


@pytest.fixture(scope="module")
def merchant_key_pair() -> tuple[rsa.RSAPrivateKey, str]:
    """商户 API 证书密钥对（请求加签侧）。"""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return private, private_pem


@pytest.fixture(scope="module")
def pay_key_pair() -> tuple[rsa.RSAPrivateKey, str]:
    """微信支付公钥密钥对（回调验签侧；公钥=平台上下载的"微信支付公钥"）。"""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_pem = private.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return private, public_pem


def _provider(
    merchant_key_pair: tuple[rsa.RSAPrivateKey, str],
    pay_key_pair: tuple[rsa.RSAPrivateKey, str],
    *,
    transport: httpx.BaseTransport | None = None,
    **overrides: str,
) -> WeChatNativePaymentProvider:
    _, private_pem = merchant_key_pair
    _, pay_public_pem = pay_key_pair
    values = {
        "wechat_appid": APPID,
        "wechat_mchid": MCHID,
        "wechat_mch_serial_no": SERIAL_NO,
        "wechat_api_v3_key": API_V3_KEY,
        "wechat_private_key_pem": private_pem,
        "wechat_public_key_id": PAY_PUBLIC_KEY_ID,
        "wechat_public_key_pem": pay_public_pem,
    }
    values.update(overrides)
    return WeChatNativePaymentProvider(SimpleNamespace(**values), transport=transport)


def _assert_authorization(
    request: httpx.Request,
    *,
    merchant_public: rsa.RSAPublicKey,
    method: str,
    path: str,
    body: str,
) -> None:
    """按 v3 文档钉 Authorization 头形状并用商户公钥验签请求串。"""
    match = _AUTH_RE.match(request.headers.get("Authorization", ""))
    assert match, f"Authorization 头形状不符: {request.headers.get('Authorization')!r}"
    assert match.group("mchid") == MCHID
    assert match.group("serial") == SERIAL_NO
    message = (
        f"{method}\n{path}\n{match.group('timestamp')}\n{match.group('nonce')}\n{body}\n"
    )
    merchant_public.verify(
        base64.b64decode(match.group("signature")),
        message.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def _make_callback(
    pay_private: rsa.RSAPrivateKey,
    *,
    plaintext: dict[str, object] | None = None,
    event_type: str = "TRANSACTION.SUCCESS",
    timestamp: str | None = None,
    serial: str = PAY_PUBLIC_KEY_ID,
    sign_with: rsa.RSAPrivateKey | None = None,
) -> tuple[bytes, dict[str, str]]:
    """自制 AES-GCM 加密信封 + 支付公钥侧签名的回调报文。"""
    if plaintext is None:
        plaintext = {
            "mchid": MCHID,
            "appid": APPID,
            "out_trade_no": ORDER["order_no"],
            "transaction_id": "4200000000000000000000000001",
            "trade_state": "SUCCESS",
            "success_time": "2026-08-22T12:00:00+08:00",
            "amount": {"total": 15900, "payer_total": 15900, "currency": "CNY"},
        }
    resource_nonce = "0123456789abcdef"
    associated_data = "transaction"
    ciphertext = AESGCM(API_V3_KEY.encode("utf-8")).encrypt(
        resource_nonce.encode("utf-8"),
        json.dumps(plaintext, ensure_ascii=False).encode("utf-8"),
        associated_data.encode("utf-8"),
    )
    body = {
        "id": "EV-2018022511223320873",
        "create_time": "2026-08-22T12:00:05+08:00",
        "event_type": event_type,
        "resource_type": "encrypt-resource",
        "summary": "支付成功",
        "resource": {
            "algorithm": "AEAD_AES_256_GCM",
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "nonce": resource_nonce,
            "associated_data": associated_data,
        },
    }
    raw_body = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ts = timestamp or str(int(time.time()))
    nonce = "5K8264ILTKCH16CQ2502SI8ZNMTM67VS"
    message = f"{ts}\n{nonce}\n{raw_body.decode('utf-8')}\n"
    signature = base64.b64encode(
        (sign_with or pay_private).sign(
            message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256()
        )
    ).decode("ascii")
    headers = {
        "Wechatpay-Timestamp": ts,
        "Wechatpay-Nonce": nonce,
        "Wechatpay-Signature": signature,
        "Wechatpay-Serial": serial,
    }
    return raw_body, headers


# ── 下单 ────────────────────────────────────────────────────────────────


def test_create_payment_posts_signed_native_order(
    merchant_key_pair: tuple[rsa.RSAPrivateKey, str],
    pay_key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    merchant_private, _ = merchant_key_pair
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"code_url": "weixin://wxpay/bizpayurl?pr=abc"})

    provider = _provider(merchant_key_pair, pay_key_pair, transport=httpx.MockTransport(handler))
    instruction = provider.create_payment(
        order=ORDER, notify_url=NOTIFY_URL, return_url=None
    )

    assert instruction.kind == "qr_code"
    assert instruction.content == "weixin://wxpay/bizpayurl?pr=abc"
    request = seen[0]
    assert request.method == "POST"
    assert request.url.path == "/v3/pay/transactions/native"
    body = request.content.decode("utf-8")
    payload = json.loads(body)
    assert payload == {
        "appid": APPID,
        "mchid": MCHID,
        "description": "AIGC Radar Membership (Yearly)",
        "out_trade_no": ORDER["order_no"],
        "notify_url": NOTIFY_URL,
        "amount": {"total": 15900, "currency": "CNY"},
    }
    _assert_authorization(
        request,
        merchant_public=merchant_private.public_key(),
        method="POST",
        path="/v3/pay/transactions/native",
        body=body,
    )


def test_create_payment_maps_upstream_rejection(
    merchant_key_pair: tuple[rsa.RSAPrivateKey, str],
    pay_key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    def rejected(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"code": "PARAM_ERROR", "message": "out_trade_no 重复"})

    provider = _provider(merchant_key_pair, pay_key_pair, transport=httpx.MockTransport(rejected))
    with pytest.raises(ChannelUpstreamError, match="PARAM_ERROR"):
        provider.create_payment(order=ORDER, notify_url=NOTIFY_URL, return_url=None)

    def no_code_url(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    provider = _provider(merchant_key_pair, pay_key_pair, transport=httpx.MockTransport(no_code_url))
    with pytest.raises(ChannelUpstreamError, match="code_url"):
        provider.create_payment(order=ORDER, notify_url=NOTIFY_URL, return_url=None)


def test_unconfigured_provider_raises(
    merchant_key_pair: tuple[rsa.RSAPrivateKey, str],
    pay_key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    provider = _provider(merchant_key_pair, pay_key_pair, wechat_public_key_id="")
    with pytest.raises(ProviderNotConfiguredError):
        provider.create_payment(order=ORDER, notify_url=NOTIFY_URL, return_url=None)
    with pytest.raises(ProviderNotConfiguredError):
        provider.query_order(order=ORDER)


# ── 回调验签 + 解密 ──────────────────────────────────────────────────────


def test_callback_round_trip(
    merchant_key_pair: tuple[rsa.RSAPrivateKey, str],
    pay_key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    pay_private, _ = pay_key_pair
    provider = _provider(merchant_key_pair, pay_key_pair)
    raw_body, headers = _make_callback(pay_private)

    verified = provider.verify_and_parse_callback(raw_body=raw_body, headers=headers)

    assert verified.order_no == ORDER["order_no"]
    assert verified.channel_order_no == "4200000000000000000000000001"
    assert verified.amount_cents == 15900
    assert verified.currency == "CNY"
    # 2026-08-22T12:00:00+08:00 → UTC
    assert verified.paid_at == datetime(2026, 8, 22, 4, 0, tzinfo=timezone.utc)


def test_callback_rejects_forged_signature(
    merchant_key_pair: tuple[rsa.RSAPrivateKey, str],
    pay_key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    pay_private, _ = pay_key_pair
    merchant_private, _ = merchant_key_pair
    provider = _provider(merchant_key_pair, pay_key_pair)
    # 用商户私钥伪造签名（验签必须用微信支付公钥才过）
    raw_body, headers = _make_callback(pay_private, sign_with=merchant_private)
    with pytest.raises(CallbackVerificationError, match="signature mismatch"):
        provider.verify_and_parse_callback(raw_body=raw_body, headers=headers)


def test_callback_rejects_public_key_id_mismatch(
    merchant_key_pair: tuple[rsa.RSAPrivateKey, str],
    pay_key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    pay_private, _ = pay_key_pair
    provider = _provider(merchant_key_pair, pay_key_pair)
    raw_body, headers = _make_callback(pay_private, serial="PUB_KEY_ID_9999")
    with pytest.raises(CallbackVerificationError, match="public key id mismatch"):
        provider.verify_and_parse_callback(raw_body=raw_body, headers=headers)


def test_callback_rejects_stale_timestamp(
    merchant_key_pair: tuple[rsa.RSAPrivateKey, str],
    pay_key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    pay_private, _ = pay_key_pair
    provider = _provider(merchant_key_pair, pay_key_pair)
    raw_body, headers = _make_callback(
        pay_private, timestamp=str(int(time.time()) - 301)
    )
    with pytest.raises(CallbackVerificationError, match="replay window"):
        provider.verify_and_parse_callback(raw_body=raw_body, headers=headers)


def test_callback_rejects_non_success_events(
    merchant_key_pair: tuple[rsa.RSAPrivateKey, str],
    pay_key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    pay_private, _ = pay_key_pair
    provider = _provider(merchant_key_pair, pay_key_pair)

    raw_body, headers = _make_callback(pay_private, event_type="TRANSACTION.CLOSED")
    with pytest.raises(CallbackVerificationError, match="not a successful transaction"):
        provider.verify_and_parse_callback(raw_body=raw_body, headers=headers)

    raw_body, headers = _make_callback(
        pay_private,
        plaintext={
            "out_trade_no": ORDER["order_no"],
            "transaction_id": "4200000000000000000000000001",
            "trade_state": "CLOSED",
            "success_time": "2026-08-22T12:00:00+08:00",
            "amount": {"total": 15900, "currency": "CNY"},
        },
    )
    with pytest.raises(CallbackVerificationError, match="not successful"):
        provider.verify_and_parse_callback(raw_body=raw_body, headers=headers)


def test_callback_rejects_currency_mismatch_and_bad_amount(
    merchant_key_pair: tuple[rsa.RSAPrivateKey, str],
    pay_key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    pay_private, _ = pay_key_pair
    provider = _provider(merchant_key_pair, pay_key_pair)

    raw_body, headers = _make_callback(
        pay_private,
        plaintext={
            "out_trade_no": ORDER["order_no"],
            "transaction_id": "4200000000000000000000000001",
            "trade_state": "SUCCESS",
            "success_time": "2026-08-22T12:00:00+08:00",
            "amount": {"total": 15900, "currency": "USD"},
        },
    )
    with pytest.raises(CallbackVerificationError, match="currency"):
        provider.verify_and_parse_callback(raw_body=raw_body, headers=headers)


def test_callback_rejects_wrong_length_api_v3_key(
    merchant_key_pair: tuple[rsa.RSAPrivateKey, str],
    pay_key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    pay_private, _ = pay_key_pair
    provider = _provider(merchant_key_pair, pay_key_pair, wechat_api_v3_key="too-short")
    raw_body, headers = _make_callback(pay_private)
    with pytest.raises(ProviderNotConfiguredError, match="32 bytes"):
        provider.verify_and_parse_callback(raw_body=raw_body, headers=headers)


# ── 查单 ────────────────────────────────────────────────────────────────


def test_query_order_sends_signed_get(
    merchant_key_pair: tuple[rsa.RSAPrivateKey, str],
    pay_key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    merchant_private, _ = merchant_key_pair
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"trade_state": "SUCCESS"})

    provider = _provider(merchant_key_pair, pay_key_pair, transport=httpx.MockTransport(handler))
    assert provider.query_order(order=ORDER) == "SUCCESS"

    request = seen[0]
    assert request.method == "GET"
    expected_path = f"/v3/pay/transactions/out-trade-no/{ORDER['order_no']}?mchid={MCHID}"
    assert request.url.path == f"/v3/pay/transactions/out-trade-no/{ORDER['order_no']}"
    assert request.url.query.decode() == f"mchid={MCHID}"
    # GET 签名串 body 段为空
    _assert_authorization(
        request,
        merchant_public=merchant_private.public_key(),
        method="GET",
        path=expected_path,
        body="",
    )


def test_query_order_maps_upstream_rejection(
    merchant_key_pair: tuple[rsa.RSAPrivateKey, str],
    pay_key_pair: tuple[rsa.RSAPrivateKey, str],
) -> None:
    def not_found(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"code": "ORDER_NOT_EXIST", "message": "订单不存在"})

    provider = _provider(merchant_key_pair, pay_key_pair, transport=httpx.MockTransport(not_found))
    with pytest.raises(ChannelUpstreamError, match="ORDER_NOT_EXIST"):
        provider.query_order(order=ORDER)
