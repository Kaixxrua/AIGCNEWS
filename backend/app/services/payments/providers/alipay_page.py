"""支付宝电脑网站支付渠道（ADR 0002，RSA2 + HTTP API）。

- create_payment：构造 ``alipay.trade.page.pay`` 跳转 URL，商户私钥 RSA2
  加签，返回 redirect_url 指令；支付宝不需要 SDK 或服务端下单请求。
- verify_and_parse_callback：对回调表单的 canonical 字符串用支付宝公钥
  RSA2 验签，成功状态才生成 VerifiedCallback；total_amount 元串在这里
  fail-closed 地归一到整数分。
- query_order：签名调用 ``alipay.trade.query``，返回支付宝 trade_status。
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import parse_qsl, urlencode

import httpx
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from fastapi import Response

from backend.app.services.payments.providers.base import (
    CallbackVerificationError,
    ChannelUpstreamError,
    PaymentInstruction,
    ProviderNotConfiguredError,
    VerifiedCallback,
)


class AlipayProviderConfig(Protocol):
    alipay_appid: str
    alipay_private_key_pem: str
    alipay_public_key_pem: str


CHANNEL_ALIPAY_PAGE = "alipay_page"
_ALIPAY_GATEWAY = "https://openapi.alipay.com/gateway.do"
_ALIPAY_CHARSET = "utf-8"
_HTTP_TIMEOUT_SECONDS = 10.0
_SHANGHAI_TZ = timezone(timedelta(hours=8))


def _config_value(config: object, *names: str) -> str:
    return next((str(value) for name in names if (value := getattr(config, name, ""))), "")


def _load_pem(value: str, armors: tuple[str, ...]) -> list[bytes]:
    """归一化密钥输入，返回待尝试的 PEM 字节串列表。

    三种形态：PEM 文本（含 BEGIN 原样使用）、文件路径（存在则读文件）、
    裸 Base64（支付宝密钥工具导出/复制的常见形态，去空白后按 armors
    依次补 PEM 头尾尝试）。
    """
    if "BEGIN" in value:
        return [value.encode("utf-8")]
    path = Path(value)
    if path.is_file():
        return [path.read_bytes()]
    body = "".join(value.split())
    return [
        f"-----BEGIN {armor}-----\n{body}\n-----END {armor}-----\n".encode("utf-8")
        for armor in armors
    ]


def _canonical_params(params: Mapping[str, Any], *, exclude_sign_type: bool = True) -> str:
    """支付宝 RSA2 待签名串：排序，剔除 sign 和空值。

    回调验签按官方规则额外剔除 sign_type（默认）；请求加签必须保留
    sign_type——网关验签串包含它（invalid-signature 报错原文可证）。
    """
    excluded = {"sign", "sign_type"} if exclude_sign_type else {"sign"}
    return "&".join(
        f"{key}={params[key]}"
        for key in sorted(params)
        if key not in excluded
        and params[key] is not None
        and str(params[key]) != ""
    )


def _sign_params(private_key: Any, params: Mapping[str, Any]) -> str:
    signature = private_key.sign(
        _canonical_params(params, exclude_sign_type=False).encode(_ALIPAY_CHARSET),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def _load_private_key(value: str) -> Any:
    # 裸 Base64 无法从外观区分 PKCS#8 / PKCS#1，两种 armor 都尝试。
    last_exc: Exception | None = None
    for pem in _load_pem(value, ("PRIVATE KEY", "RSA PRIVATE KEY")):
        try:
            return serialization.load_pem_private_key(pem, password=None)
        except (OSError, ValueError, TypeError) as exc:
            last_exc = exc
    raise ProviderNotConfiguredError("alipay private key is unavailable") from last_exc


def _load_public_key(value: str) -> Any:
    last_exc: Exception | None = None
    for pem in _load_pem(value, ("PUBLIC KEY", "RSA PUBLIC KEY")):
        try:
            return serialization.load_pem_public_key(pem)
        except (OSError, ValueError, TypeError) as exc:
            last_exc = exc
    raise CallbackVerificationError("alipay public key is unavailable") from last_exc


def _product_name(order: Mapping[str, Any]) -> str:
    if str(order.get("plan_code", "")).endswith("yearly"):
        return "AIGC Radar Membership (Yearly)"
    return "AIGC Radar Membership (Monthly)"


def _amount_yuan(amount_cents: object) -> str:
    try:
        cents = int(amount_cents)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid payment amount") from exc
    if cents <= 0:
        raise ValueError("payment amount must be positive")
    return f"{Decimal(cents) / Decimal(100):.2f}"


def _return_url(order: Mapping[str, Any], return_url: str | None) -> str | None:
    if not return_url:
        return None
    order_no = str(order["order_no"])
    plan = "yearly" if str(order.get("plan_code", "")).endswith("yearly") else "monthly"
    separator = "&" if "?" in return_url else "?"
    return f"{return_url}{separator}{urlencode({'order_no': order_no, 'plan': plan})}"


def _yuan_to_cents(value: object) -> int:
    """把支付宝元串严格归一到分；超过两位小数一律拒绝。"""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CallbackVerificationError("invalid alipay total_amount") from exc
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        raise CallbackVerificationError("alipay amount must have at most two decimals")
    cents = amount * 100
    if cents != cents.to_integral_value():
        raise CallbackVerificationError("alipay amount is not representable in cents")
    return int(cents)


def _parse_paid_at(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise CallbackVerificationError("missing alipay gmt_payment")
    try:
        # 支付宝 gmt_payment 是中国标准时间；内部统一保存 UTC aware。
        local = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=_SHANGHAI_TZ)
    except ValueError as exc:
        raise CallbackVerificationError("invalid alipay gmt_payment") from exc
    return local.astimezone(timezone.utc)


class AlipayPagePaymentProvider:
    """支付宝电脑网站支付渠道；凭证未齐时全部能力 503。"""

    channel = CHANNEL_ALIPAY_PAGE

    def __init__(
        self,
        settings: AlipayProviderConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport

    def is_configured(self) -> bool:
        return all(
            [
                _config_value(self._settings, "alipay_appid"),
                _config_value(self._settings, "alipay_private_key_pem", "alipay_private_key_path"),
                _config_value(self._settings, "alipay_public_key_pem", "alipay_public_key_path"),
            ]
        )

    def create_payment(
        self,
        *,
        order: Mapping[str, Any],
        notify_url: str,
        return_url: str | None,
        shopper_ip: str | None = None,
    ) -> PaymentInstruction:
        del shopper_ip  # 本渠道无需下单人 IP（PingPong 等海外渠道必填）
        if not self.is_configured():
            raise ProviderNotConfiguredError("alipay_page channel not configured")
        private_key = _load_private_key(
            _config_value(self._settings, "alipay_private_key_pem", "alipay_private_key_path")
        )
        params: dict[str, str] = {
            "app_id": _config_value(self._settings, "alipay_appid"),
            "method": "alipay.trade.page.pay",
            "charset": _ALIPAY_CHARSET,
            "sign_type": "RSA2",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "notify_url": notify_url,
            "biz_content": json.dumps(
                {
                    "out_trade_no": str(order["order_no"]),
                    "total_amount": _amount_yuan(order["amount_cents"]),
                    "subject": _product_name(order),
                    "product_code": "FAST_INSTANT_TRADE_PAY",
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
        callback_url = _return_url(order, return_url)
        if callback_url:
            params["return_url"] = callback_url
        params["sign"] = _sign_params(private_key, params)
        return PaymentInstruction(
            kind="redirect_url",
            content=f"{_ALIPAY_GATEWAY}?{urlencode(params)}",
        )

    def verify_and_parse_callback(
        self,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> VerifiedCallback:
        if not self.is_configured():
            raise ProviderNotConfiguredError("alipay_page channel not configured")
        try:
            fields = dict(parse_qsl(raw_body.decode("utf-8"), keep_blank_values=True))
        except (UnicodeDecodeError, ValueError) as exc:
            raise CallbackVerificationError("invalid alipay callback encoding") from exc
        signature = fields.get("sign", "")
        if not signature or fields.get("sign_type") != "RSA2":
            raise CallbackVerificationError("missing alipay RSA2 signature")
        public_key = _load_public_key(
            _config_value(self._settings, "alipay_public_key_pem", "alipay_public_key_path")
        )
        try:
            decoded_signature = base64.b64decode(signature, validate=True)
            public_key.verify(
                decoded_signature,
                _canonical_params(fields).encode(_ALIPAY_CHARSET),
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (InvalidSignature, ValueError, TypeError) as exc:
            raise CallbackVerificationError("alipay callback signature mismatch") from exc
        if fields.get("app_id") != _config_value(self._settings, "alipay_appid"):
            raise CallbackVerificationError("alipay app_id mismatch")
        if fields.get("trade_status") not in {"TRADE_SUCCESS", "TRADE_FINISHED"}:
            raise CallbackVerificationError("alipay trade is not successful")
        order_no = fields.get("out_trade_no")
        channel_order_no = fields.get("trade_no")
        if not order_no or not channel_order_no:
            raise CallbackVerificationError("alipay callback missing order identifiers")
        return VerifiedCallback(
            order_no=order_no,
            channel_order_no=channel_order_no,
            amount_cents=_yuan_to_cents(fields.get("total_amount")),
            currency="CNY",
            paid_at=_parse_paid_at(fields.get("gmt_payment")),
        )

    def build_ack_response(self, *, ok: bool) -> Response:
        # 支付宝应答契约：纯文本 success/failure（收到 failure 或非 2xx 会重发）。
        return Response(
            content="success" if ok else "failure",
            status_code=200 if ok else 400,
            media_type="text/plain",
        )

    def query_order(self, *, order: Mapping[str, Any]) -> str:
        if not self.is_configured():
            raise ProviderNotConfiguredError("alipay_page channel not configured")
        private_key = _load_private_key(
            _config_value(self._settings, "alipay_private_key_pem", "alipay_private_key_path")
        )
        params: dict[str, str] = {
            "app_id": _config_value(self._settings, "alipay_appid"),
            "method": "alipay.trade.query",
            "charset": _ALIPAY_CHARSET,
            "sign_type": "RSA2",
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0",
            "biz_content": json.dumps(
                {"out_trade_no": str(order["order_no"])},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
        params["sign"] = _sign_params(private_key, params)
        try:
            with httpx.Client(transport=self._transport, timeout=_HTTP_TIMEOUT_SECONDS) as client:
                response = client.post(_ALIPAY_GATEWAY, data=params)
        except httpx.HTTPError as exc:
            raise ChannelUpstreamError(f"alipay trade query request failed: {exc}") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise ChannelUpstreamError(f"alipay trade query rejected: HTTP {response.status_code}")
        try:
            payload = response.json()
            result = payload["alipay_trade_query_response"]
            if not isinstance(result, dict):
                raise TypeError
        except (ValueError, KeyError, TypeError) as exc:
            raise ChannelUpstreamError("alipay trade query returned invalid response") from exc
        trade_status = result.get("trade_status")
        if not isinstance(trade_status, str) or not trade_status:
            raise ChannelUpstreamError(
                f"alipay trade query failed: {result.get('sub_msg') or result.get('msg') or 'unknown error'}"
            )
        return trade_status
