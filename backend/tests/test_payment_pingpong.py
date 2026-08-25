"""PingPongCheckout v4 渠道契约测试（overseas_redirect 服务商实现之一）。

钉住的对外语义（全部取自官方 v4 文档，无沙箱实测——见 docs/payments.md）：
- prePay 报文：信封公共参数（accId/clientId/signType/version）+
  bizContent JSON 字符串；签名 = SHA256(盐 + 键 ASCII 升序 key=value&...)
  大写 hex，sign 字段不参与；goods[].imgUrl 必填；shopperIP 必填且限 IPv4；
- 同步应答：code == "000000" 才受理；带 sign 必验签（篡改即拒）、缺 sign
  告警放行（无沙箱期容错，错误码仍会抛 ChannelUpstreamError）；
- 回调：验签对齐官方 PHP 参考（原始文本转义归一 → JSON 解析 → 顶层字段
  全字符串 → 排序盐置首哈希 → compare_digest）；clientId/accId 归属钉死；
  code=="000000" 且 notifyType=="RECHARGE" 且 status=="SUCCESS" 才产出
  VerifiedCallback；其余一律 None（验签通过但非终态 → ACK 200 终止重发）；
- ACK：HTTP 200 纯文本 ``OK`` / 400 ``FAIL``（2xx 且非 FAIL 即成功）；
- 凭证不齐 → 全部能力 ProviderNotConfiguredError（路由 503）。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from backend.app.services.payments.providers.base import (
    CallbackVerificationError,
    ChannelUpstreamError,
    ProviderNotConfiguredError,
)
from backend.app.services.payments.providers.pingpong import (
    PingPongProvider,
    _amount_str,
    _amount_to_cents,
    _normalize_callback_text,
    _sign_content,
)

CLIENT_ID = "pp-client-id-001"
SALT = "pp-sign-salt-001"
ACC_ID = "pp-acc-id-001"
ORDER = {
    "order_no": "P20260825120000ABC123",
    "plan_code": "member_monthly",
    "amount_cents": 1900,
    "currency": "usd",
}


def _provider(
    transport: httpx.BaseTransport | None = None,
    *,
    sandbox: bool = True,
    client_id: str = CLIENT_ID,
    salt: str = SALT,
    acc_id: str = ACC_ID,
    public_base_url: str = "https://pay.example.test",
) -> PingPongProvider:
    return PingPongProvider(
        SimpleNamespace(
            overseas_provider="pingpong",
            overseas_sandbox=sandbox,
            overseas_client_id=client_id,
            overseas_client_secret=salt,
            overseas_webhook_secret=acc_id,
            public_base_url=public_base_url,
        ),
        transport=transport,
    )


def _notification_payload(
    *,
    status: str = "SUCCESS",
    notify_type: str = "RECHARGE",
    code: str = "000000",
    amount: str = "19.000000",
    order_no: str = ORDER["order_no"],
) -> dict:
    biz = {
        "merchantTransactionId": order_no,
        "transactionId": "PP-TXN-1",
        "amount": amount,
        "currency": "usd",
        "status": status,
        "notifyType": notify_type,
        "transactionTime": 1781116800000,
        "transactionEndTime": 1781116810000,
    }
    payload = {
        "accId": ACC_ID,
        "clientId": CLIENT_ID,
        "code": code,
        "description": "Transaction succeeded",
        "signType": "SHA256",
        "bizContent": json.dumps(biz, ensure_ascii=False, separators=(",", ":")),
    }
    payload["sign"] = _sign_content(payload, salt=SALT, sign_type="SHA256")
    return payload


def _raw(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


class _PingPongApi:
    """编排化上游替身：验本端签名 + 按场景应答（应答按需带 sign）。"""

    def __init__(
        self,
        *,
        biz: dict | None = None,
        code: str = "000000",
        http_status: int = 200,
        sign_response: bool = True,
    ) -> None:
        self.biz = biz if biz is not None else {"paymentUrl": "https://cashier.pingpongx.test/pay/1"}
        self.code = code
        self.http_status = http_status
        self.sign_response = sign_response
        self.requests: list[dict] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        envelope = json.loads(request.content)
        self.requests.append(envelope)
        # 本端加签自证：用同一盐重算必须一致（否则说明装配被破坏）
        expected = _sign_content(
            {k: v for k, v in envelope.items() if k != "sign"}, salt=SALT, sign_type="SHA256"
        )
        assert envelope["sign"] == expected, "outbound envelope signature mismatch"
        response = {
            "accId": ACC_ID,
            "clientId": CLIENT_ID,
            "signType": "SHA256",
            "code": self.code,
            "description": "ok" if self.code == "000000" else "rejected",
            "bizContent": json.dumps(self.biz, ensure_ascii=False, separators=(",", ":")),
        }
        if self.sign_response:
            response["sign"] = _sign_content(response, salt=SALT, sign_type="SHA256")
        return httpx.Response(self.http_status, json=response)


# ── 签名串装配 ───────────────────────────────────────────────────────────


def test_sign_content_sorts_keys_prepends_salt_and_excludes_sign() -> None:
    fields = {"b": "2", "a": "1", "sign": "SHOULD-NOT-PARTICIPATE"}
    expected = _sign_content({"a": "1", "b": "2"}, salt=SALT, sign_type="SHA256")
    assert _sign_content(fields, salt=SALT, sign_type="SHA256") == expected
    # 盐置首语义：同样的字段换盐必变
    assert _sign_content({"a": "1", "b": "2"}, salt="other-salt", sign_type="SHA256") != expected
    # 大写 hex
    assert expected == expected.upper()
    assert len(expected) == 64


def test_sign_content_supports_md5_and_rejects_unknown_sign_type() -> None:
    md5 = _sign_content({"a": "1"}, salt=SALT, sign_type="MD5")
    assert len(md5) == 32 and md5 == md5.upper()
    with pytest.raises(CallbackVerificationError, match="signType"):
        _sign_content({"a": "1"}, salt=SALT, sign_type="RSA")


def test_normalize_callback_text_aligns_php_reference_escapes() -> None:
    raw = '{"bizContent":"line1\\nline2\\t\\\\\"quoted\\\\\""}'
    normalized = _normalize_callback_text(raw.encode())
    assert '\\\\n' in normalized  # \n → \\n
    assert '\\\\t' in normalized
    assert '\\\\\\"' in normalized  # \\" → \\\"
    # 归一后 JSON 解析得到的是渠道加签时的字面形态（\n 为两字符原样，非换行）——
    # 官方 PHP 参考正是用这个字面形态参与验签。
    assert json.loads(normalized)["bizContent"] == 'line1\\nline2\\t\\"quoted\\"'


# ── prePay 下单报文 ──────────────────────────────────────────────────────


def test_create_payment_posts_signed_envelope_and_returns_payment_url() -> None:
    api = _PingPongApi()
    expires = datetime(2026, 8, 25, 12, 30, tzinfo=timezone.utc)
    instruction = _provider(api.transport()).create_payment(
        order={**ORDER, "expires_at": expires},
        notify_url="https://pay.example.test/api/payments/callback/overseas_redirect",
        return_url="https://pay.example.test/membership/checkout",
        shopper_ip="203.0.113.7",
    )

    assert instruction.kind == "redirect_url"
    assert instruction.content == "https://cashier.pingpongx.test/pay/1"

    assert len(api.requests) == 1
    envelope = api.requests[0]
    # 信封公共参数钉
    assert envelope["accId"] == ACC_ID
    assert envelope["clientId"] == CLIENT_ID
    assert envelope["signType"] == "SHA256"
    assert envelope["version"] == "1.0"
    biz = json.loads(envelope["bizContent"])
    assert biz["captureDelayHours"] == 0  # 立即捕获
    assert biz["amount"] == "19.00"
    assert biz["currency"] == "USD"
    # merchantTransactionId = order_no：官方约定同单号参数不可变更，天然幂等
    assert biz["merchantTransactionId"] == ORDER["order_no"]
    assert biz["notificationUrl"] == "https://pay.example.test/api/payments/callback/overseas_redirect"
    assert (
        biz["payResultUrl"]
        == "https://pay.example.test/membership/checkout?order_no=P20260825120000ABC123&plan=monthly"
    )
    assert biz["payCancelUrl"] == biz["payResultUrl"]
    assert biz["shopperIP"] == "203.0.113.7"
    assert biz["timeExpire"] == str(int(expires.timestamp()))
    goods = biz["goods"][0]
    assert goods["name"] == "AIGC Radar Membership - Monthly"
    assert goods["unitPrice"] == "19.00"
    assert goods["number"] == "1"
    # imgUrl 官方必填：取公网基址下的静态 logo
    assert goods["imgUrl"] == "https://pay.example.test/logo.png"


def test_create_payment_requires_ipv4_shopper_ip() -> None:
    provider = _provider(_PingPongApi().transport())
    for bad in ("", "unknown", "not-an-ip", "2001:db8::1"):
        with pytest.raises(ChannelUpstreamError, match="shopper ipv4"):
            provider.create_payment(
                order=ORDER,
                notify_url="https://pay.example.test/cb",
                return_url=None,
                shopper_ip=bad,
            )


def test_create_payment_maps_rejection_and_http_failure_to_upstream_error() -> None:
    api = _PingPongApi(code="100001")
    with pytest.raises(ChannelUpstreamError, match="100001"):
        _provider(api.transport()).create_payment(
            order=ORDER, notify_url="https://pay.example.test/cb", return_url=None,
            shopper_ip="203.0.113.7",
        )

    api = _PingPongApi(http_status=502)
    with pytest.raises(ChannelUpstreamError, match="HTTP 502"):
        _provider(api.transport()).create_payment(
            order=ORDER, notify_url="https://pay.example.test/cb", return_url=None,
            shopper_ip="203.0.113.7",
        )


def test_response_signature_tampering_rejected_missing_sign_warned_but_accepted() -> None:
    # 缺 sign：告警放行（无沙箱期容错），成功码仍正常产出指令
    api = _PingPongApi(sign_response=False)
    instruction = _provider(api.transport()).create_payment(
        order=ORDER, notify_url="https://pay.example.test/cb", return_url=None,
        shopper_ip="203.0.113.7",
    )
    assert instruction.kind == "redirect_url"

    # 篡改应答（签名对不上）：一律拒绝
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "accId": ACC_ID, "clientId": CLIENT_ID, "signType": "SHA256",
            "code": "000000", "description": "ok",
            "bizContent": json.dumps({"paymentUrl": "https://cashier.pingpongx.test/pay/1"}),
            "sign": "0" * 64,
        })

    with pytest.raises(ChannelUpstreamError, match="signature mismatch"):
        _provider(httpx.MockTransport(handler)).create_payment(
            order=ORDER, notify_url="https://pay.example.test/cb", return_url=None,
            shopper_ip="203.0.113.7",
        )


# ── 回调：验签 + 状态映射 ────────────────────────────────────────────────


def test_callback_success_round_trip_yields_verified_callback() -> None:
    payload = _notification_payload()
    verified = _provider().verify_and_parse_callback(raw_body=_raw(payload), headers={})

    assert verified is not None
    assert verified.order_no == ORDER["order_no"]
    assert verified.channel_order_no == "PP-TXN-1"
    assert verified.amount_cents == 1900  # "19.000000" 归一到分
    assert verified.currency == "USD"
    # transactionEndTime 毫秒 → UTC
    assert verified.paid_at == datetime.fromtimestamp(1781116810000 / 1000, tz=timezone.utc)


def test_callback_non_terminal_states_and_non_recharge_return_none() -> None:
    provider = _provider()
    for status in ("INIT", "PROCESSING", "FAILED", "AUTH_SUCCESS", "CANCEL", "CLOSED"):
        payload = _notification_payload(status=status)
        assert provider.verify_and_parse_callback(raw_body=_raw(payload), headers={}) is None, status
    # 非支付结果通知（本渠道只订 RECHARGE）
    payload = _notification_payload(notify_type="REFUND")
    assert provider.verify_and_parse_callback(raw_body=_raw(payload), headers={}) is None
    # 业务码非成功
    payload = _notification_payload(code="100001")
    assert provider.verify_and_parse_callback(raw_body=_raw(payload), headers={}) is None


def test_callback_rejects_signature_mismatch_and_identity_drift() -> None:
    provider = _provider()
    payload = _notification_payload()
    payload["sign"] = "0" * 64
    with pytest.raises(CallbackVerificationError, match="signature mismatch"):
        provider.verify_and_parse_callback(raw_body=_raw(payload), headers={})

    # 归属漂移：报文用别的商户号加签（验签本身可能过），clientId/accId 钉死拦截
    drifted = _notification_payload()
    drifted["clientId"] = "other-merchant"
    drifted["sign"] = _sign_content(
        {k: v for k, v in drifted.items() if k != "sign"}, salt=SALT, sign_type="SHA256"
    )
    with pytest.raises(CallbackVerificationError, match="identity mismatch"):
        provider.verify_and_parse_callback(raw_body=_raw(drifted), headers={})

    drifted_acc = _notification_payload()
    drifted_acc["accId"] = "other-store"
    drifted_acc["sign"] = _sign_content(
        {k: v for k, v in drifted_acc.items() if k != "sign"}, salt=SALT, sign_type="SHA256"
    )
    with pytest.raises(CallbackVerificationError, match="identity mismatch"):
        provider.verify_and_parse_callback(raw_body=_raw(drifted_acc), headers={})


def test_callback_rejects_missing_signature_and_non_string_fields() -> None:
    provider = _provider()
    payload = _notification_payload()
    del payload["sign"]
    with pytest.raises(CallbackVerificationError, match="signature"):
        provider.verify_and_parse_callback(raw_body=_raw(payload), headers={})

    # 官方通知顶层字段全为字符串；出现结构化字段即与契约不符
    payload = _notification_payload()
    payload["bizContent"] = json.loads(payload["bizContent"])
    payload["sign"] = _sign_content(
        {k: v for k, v in payload.items() if k != "sign" and isinstance(v, str)},
        salt=SALT, sign_type="SHA256",
    )
    with pytest.raises(CallbackVerificationError, match="not a string"):
        provider.verify_and_parse_callback(raw_body=_raw(payload), headers={})


def test_callback_amount_fail_closed() -> None:
    provider = _provider()
    for bad in ("19.001", "abc", "", "0", "-1"):
        payload = _notification_payload(amount=bad)
        with pytest.raises(CallbackVerificationError):
            provider.verify_and_parse_callback(raw_body=_raw(payload), headers={})


def test_amount_helpers() -> None:
    assert _amount_str(1900) == "19.00"
    assert _amount_to_cents(Decimal("19.000000")) == 1900
    with pytest.raises(ValueError):
        _amount_str(0)


# ── is_configured / ACK / query ──────────────────────────────────────────


def test_unconfigured_capabilities_raise_provider_not_configured() -> None:
    provider = _provider(salt="")
    assert provider.is_configured() is False
    with pytest.raises(ProviderNotConfiguredError):
        provider.create_payment(
            order=ORDER, notify_url="https://x/cb", return_url=None, shopper_ip="203.0.113.7"
        )
    with pytest.raises(ProviderNotConfiguredError):
        provider.verify_and_parse_callback(raw_body=b"{}", headers={})
    with pytest.raises(ProviderNotConfiguredError):
        provider.query_order(order=ORDER)
    # 三凭证缺一不可（clientId / 签名盐 / accId）
    assert _provider(client_id="").is_configured() is False
    assert _provider(acc_id="").is_configured() is False


def test_ack_contract_is_plain_text_ok() -> None:
    provider = _provider()
    ok = provider.build_ack_response(ok=True)
    assert ok.status_code == 200
    assert bytes(ok.body) == b"OK"
    assert ok.media_type == "text/plain"
    fail = provider.build_ack_response(ok=False)
    assert fail.status_code == 400
    assert bytes(fail.body) == b"FAIL"


def test_query_order_returns_status() -> None:
    api = _PingPongApi(biz={"status": "SUCCESS", "transactionId": "PP-TXN-1"})
    status = _provider(api.transport()).query_order(order=ORDER)
    assert status == "SUCCESS"
    envelope = api.requests[0]
    biz = json.loads(envelope["bizContent"])
    assert biz == {"merchantTransactionId": ORDER["order_no"]}


def test_live_mode_uses_fra_api_base() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        response = {
            "accId": ACC_ID, "clientId": CLIENT_ID, "signType": "SHA256",
            "code": "000000", "description": "ok",
            "bizContent": json.dumps({"paymentUrl": "https://cashier.pingpongx.test/pay/1"}),
        }
        response["sign"] = _sign_content(response, salt=SALT, sign_type="SHA256")
        return httpx.Response(200, json=response)

    _provider(httpx.MockTransport(handler), sandbox=False).create_payment(
        order=ORDER, notify_url="https://pay.example.test/cb", return_url=None,
        shopper_ip="203.0.113.7",
    )
    assert captured["url"].startswith("https://acquirer-payment.pingpongx.com/v4/payment/prePay")
