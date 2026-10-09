"""微信支付 Native 扫码渠道（ADR 0002，v3 API + 微信支付公钥验签）。

- create_payment：POST /v3/pay/transactions/native，商户 API 证书私钥按
  ``{method}\\n{path}\\n{timestamp}\\n{nonce}\\n{body}\\n`` 串 RSA-SHA256
  加签（Authorization: WECHATPAY2-SHA256-RSA2048），取 code_url 作为
  qr_code 指令；金额直接以分传给 amount.total。
- verify_and_parse_callback：Wechatpay-Timestamp/Nonce/Signature/Serial
  头对 raw_body 原始字节验签——验签串 ``{ts}\\n{nonce}\\n{body}\\n`` 用
  **微信支付公钥**（商户平台一次性下载、静态配置，避开平台证书轮换运维）
  RSA-SHA256 验；Serial 头必须等于配置的公钥 ID；±5 分钟防重放；
  resource 为 AEAD_AES_256_GCM，用 API v3 密钥解密后取
  out_trade_no/transaction_id/amount.total/success_time。
- query_order：GET /v3/pay/transactions/out-trade-no/{order_no}（GET 签名
  串 body 段为空），返回 trade_state。
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

import httpx
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Response
from fastapi.responses import JSONResponse

from backend.app.services.payments.providers.base import (
    CallbackVerificationError,
    ChannelUpstreamError,
    PaymentInstruction,
    ProviderNotConfiguredError,
    VerifiedCallback,
)


class WeChatProviderConfig(Protocol):
    wechat_appid: str
    wechat_mchid: str
    wechat_mch_serial_no: str
    wechat_api_v3_key: str
    wechat_private_key_pem: str
    wechat_public_key_id: str
    wechat_public_key_pem: str


CHANNEL_WECHAT_NATIVE = "wechat_native"
_WECHAT_API_BASE = "https://api.mch.weixin.qq.com"
_NATIVE_PATH = "/v3/pay/transactions/native"
_HTTP_TIMEOUT_SECONDS = 10.0
# 微信 v3 防重放窗口：±5 分钟
_REPLAY_TOLERANCE_SECONDS = 300
_AUTH_SCHEME = "WECHATPAY2-SHA256-RSA2048"


def _config_value(config: object, *names: str) -> str:
    return next((str(value) for name in names if (value := getattr(config, name, ""))), "")


def _load_pem(value: str, armors: tuple[str, ...]) -> list[bytes]:
    """归一化密钥输入（与支付宝渠道同三形态：PEM 文本 / 文件路径 / 裸 Base64）。"""
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


def _load_private_key(value: str) -> Any:
    last_exc: Exception | None = None
    for pem in _load_pem(value, ("PRIVATE KEY", "RSA PRIVATE KEY")):
        try:
            return serialization.load_pem_private_key(pem, password=None)
        except (OSError, ValueError, TypeError) as exc:
            last_exc = exc
    raise ProviderNotConfiguredError("wechat private key is unavailable") from last_exc


def _load_pay_public_key(value: str) -> Any:
    last_exc: Exception | None = None
    for pem in _load_pem(value, ("PUBLIC KEY", "RSA PUBLIC KEY")):
        try:
            return serialization.load_pem_public_key(pem)
        except (OSError, ValueError, TypeError) as exc:
            last_exc = exc
    raise CallbackVerificationError("wechat pay public key is unavailable") from last_exc


def _product_name(order: Mapping[str, Any]) -> str:
    if str(order.get("plan_code", "")).endswith("yearly"):
        return "AIGC Radar Membership (Yearly)"
    return "AIGC Radar Membership (Monthly)"


def _amount_cents(order: Mapping[str, Any]) -> int:
    try:
        cents = int(order["amount_cents"])
    except (TypeError, ValueError, KeyError) as exc:
        raise ValueError("invalid payment amount") from exc
    if cents <= 0:
        raise ValueError("payment amount must be positive")
    return cents


def _sign_message(private_key: Any, message: str) -> str:
    signature = private_key.sign(
        message.encode("utf-8"), padding.PKCS1v15(), hashes.SHA256()
    )
    return base64.b64encode(signature).decode("ascii")


def _authorization_header(
    *, private_key: Any, mchid: str, serial_no: str, method: str, path: str, body: str
) -> str:
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    message = f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n"
    signature = _sign_message(private_key, message)
    return (
        f'{_AUTH_SCHEME} mchid="{mchid}",nonce_str="{nonce}",'
        f'signature="{signature}",timestamp="{timestamp}",serial_no="{serial_no}"'
    )


def _parse_success_time(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise CallbackVerificationError("missing wechat success_time")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise CallbackVerificationError("invalid wechat success_time") from exc
    if parsed.tzinfo is None:
        raise CallbackVerificationError("wechat success_time must carry a timezone")
    return parsed.astimezone(timezone.utc)


class WeChatNativePaymentProvider:
    """WeChat Pay v3 Native（扫码）渠道；凭证未齐时全部能力 503。"""

    channel = CHANNEL_WECHAT_NATIVE

    def __init__(
        self,
        settings: WeChatProviderConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport

    def is_configured(self) -> bool:
        return all(
            [
                _config_value(self._settings, "wechat_appid", "wechat_pay_appid"),
                _config_value(self._settings, "wechat_mchid", "wechat_pay_mchid"),
                _config_value(self._settings, "wechat_mch_serial_no", "wechat_pay_mch_serial_no"),
                _config_value(self._settings, "wechat_api_v3_key", "wechat_pay_api_v3_key"),
                _config_value(
                    self._settings, "wechat_private_key_pem", "wechat_pay_private_key_path"
                ),
                _config_value(self._settings, "wechat_public_key_id", "wechat_pay_public_key_id"),
                _config_value(
                    self._settings, "wechat_public_key_pem", "wechat_pay_public_key_path"
                ),
            ]
        )

    def _require_private_key(self) -> Any:
        if not self.is_configured():
            raise ProviderNotConfiguredError("wechat_native channel not configured")
        return _load_private_key(
            _config_value(self._settings, "wechat_private_key_pem", "wechat_pay_private_key_path")
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
        private_key = self._require_private_key()
        mchid = _config_value(self._settings, "wechat_mchid", "wechat_pay_mchid")
        body = json.dumps(
            {
                "appid": _config_value(self._settings, "wechat_appid", "wechat_pay_appid"),
                "mchid": mchid,
                "description": _product_name(order),
                "out_trade_no": str(order["order_no"]),
                "notify_url": notify_url,
                # Native 扫码在微信侧完成支付，无前台回跳，return_url 刻意不用
                "amount": {"total": _amount_cents(order), "currency": "CNY"},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        authorization = _authorization_header(
            private_key=private_key,
            mchid=mchid,
            serial_no=_config_value(
                self._settings, "wechat_mch_serial_no", "wechat_pay_mch_serial_no"
            ),
            method="POST",
            path=_NATIVE_PATH,
            body=body,
        )
        try:
            with httpx.Client(transport=self._transport, timeout=_HTTP_TIMEOUT_SECONDS) as client:
                response = client.post(
                    f"{_WECHAT_API_BASE}{_NATIVE_PATH}",
                    content=body.encode("utf-8"),
                    headers={
                        "Authorization": authorization,
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                        "Wechatpay-Serial": _config_value(
                            self._settings, "wechat_public_key_id", "wechat_pay_public_key_id"
                        ),
                    },
                )
        except httpx.HTTPError as exc:
            raise ChannelUpstreamError(f"wechat native pay request failed: {exc}") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise ChannelUpstreamError(
                f"wechat native pay rejected: HTTP {response.status_code} "
                f"{_upstream_message(response)}"
            )
        self._verify_response(response)
        try:
            payload = response.json()
            code_url = payload["code_url"]
            # 官方示例还包含 /bizpayurl/up?...，不能只接受旧版无子路径链接。
            if not isinstance(code_url, str) or not code_url.startswith(
                ("weixin://wxpay/bizpayurl?", "weixin://wxpay/bizpayurl/")
            ):
                raise TypeError
        except (ValueError, KeyError, TypeError) as exc:
            raise ChannelUpstreamError("wechat native pay returned no code_url") from exc
        return PaymentInstruction(kind="qr_code", content=code_url)

    def _verify_signature(self, raw_body: bytes, headers: Mapping[str, str]) -> None:
        """API 应答和通知都对原始字节验签，共用公钥归属与防重放检查。"""
        header_map = {key.lower(): value for key, value in headers.items()}
        timestamp = header_map.get("wechatpay-timestamp", "")
        nonce = header_map.get("wechatpay-nonce", "")
        signature = header_map.get("wechatpay-signature", "")
        serial = header_map.get("wechatpay-serial", "")
        if not all([timestamp, nonce, signature, serial]):
            raise CallbackVerificationError("missing wechat signature headers")
        # 公钥模式下 Serial 头即微信支付公钥 ID，钉死归属再验签
        if serial != _config_value(
            self._settings, "wechat_public_key_id", "wechat_pay_public_key_id"
        ):
            raise CallbackVerificationError("wechat pay public key id mismatch")
        try:
            signed_at = int(timestamp)
        except ValueError as exc:
            raise CallbackVerificationError("invalid wechat timestamp") from exc
        if abs(time.time() - signed_at) > _REPLAY_TOLERANCE_SECONDS:
            raise CallbackVerificationError("wechat callback outside replay window")
        public_key = _load_pay_public_key(
            _config_value(self._settings, "wechat_public_key_pem", "wechat_pay_public_key_path")
        )
        try:
            decoded_signature = base64.b64decode(signature, validate=True)
            message = f"{timestamp}\n{nonce}\n".encode("utf-8") + raw_body + b"\n"
            public_key.verify(
                decoded_signature,
                message,
                padding.PKCS1v15(),
                hashes.SHA256(),
            )
        except (InvalidSignature, ValueError, TypeError, UnicodeDecodeError) as exc:
            raise CallbackVerificationError("wechat callback signature mismatch") from exc

    def _verify_response(self, response: httpx.Response) -> None:
        try:
            self._verify_signature(response.content, response.headers)
        except CallbackVerificationError as exc:
            raise ChannelUpstreamError("wechat response signature verification failed") from exc

    def verify_and_parse_callback(
        self,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> VerifiedCallback:
        if not self.is_configured():
            raise ProviderNotConfiguredError("wechat_native channel not configured")
        self._verify_signature(raw_body, headers)
        try:
            body = json.loads(raw_body)
            if not isinstance(body, dict):
                raise TypeError
            resource = body["resource"]
            if not isinstance(resource, dict):
                raise TypeError
        except (ValueError, KeyError, TypeError) as exc:
            raise CallbackVerificationError("invalid wechat callback body") from exc
        if body.get("event_type") != "TRANSACTION.SUCCESS":
            raise CallbackVerificationError("wechat callback is not a successful transaction")
        plaintext = self._decrypt_resource(resource)
        for field in ("appid", "mchid"):
            if plaintext.get(field) != _config_value(
                self._settings, f"wechat_{field}", f"wechat_pay_{field}"
            ):
                raise CallbackVerificationError(f"wechat callback {field} mismatch")
        return self._to_verified_callback(plaintext)

    def _decrypt_resource(self, resource: Mapping[str, Any]) -> dict[str, Any]:
        if resource.get("algorithm") != "AEAD_AES_256_GCM":
            raise CallbackVerificationError("unsupported wechat resource algorithm")
        api_v3_key = _config_value(self._settings, "wechat_api_v3_key", "wechat_pay_api_v3_key")
        key_bytes = api_v3_key.encode("utf-8")
        if len(key_bytes) != 32:
            raise ProviderNotConfiguredError("wechat api_v3 key must be 32 bytes")
        ciphertext_b64 = resource.get("ciphertext")
        nonce = resource.get("nonce")
        associated_data = resource.get("associated_data")
        if not all(
            isinstance(value, str) and value for value in (ciphertext_b64, nonce, associated_data)
        ):
            raise CallbackVerificationError("wechat resource missing ciphertext fields")
        try:
            ciphertext = base64.b64decode(str(ciphertext_b64), validate=True)
            # 微信密文 base64 尾部已附 16 字节 GCM tag，与 AESGCM.decrypt 输入约定一致
            plaintext = AESGCM(key_bytes).decrypt(
                str(nonce).encode("utf-8"), ciphertext, str(associated_data).encode("utf-8")
            )
            parsed = json.loads(plaintext)
            if not isinstance(parsed, dict):
                raise TypeError
            return parsed
        except (InvalidTag, ValueError, TypeError) as exc:
            raise CallbackVerificationError("wechat resource decryption failed") from exc

    @staticmethod
    def _to_verified_callback(plaintext: Mapping[str, Any]) -> VerifiedCallback:
        if plaintext.get("trade_state") != "SUCCESS":
            raise CallbackVerificationError("wechat trade is not successful")
        order_no = plaintext.get("out_trade_no")
        channel_order_no = plaintext.get("transaction_id")
        if not order_no or not channel_order_no:
            raise CallbackVerificationError("wechat callback missing order identifiers")
        amount = plaintext.get("amount")
        if not isinstance(amount, Mapping):
            raise CallbackVerificationError("wechat callback missing amount")
        if amount.get("currency") != "CNY":
            raise CallbackVerificationError("wechat amount currency mismatch")
        total = amount.get("total")
        if type(total) is not int:
            raise CallbackVerificationError("invalid wechat amount.total")
        if total <= 0:
            raise CallbackVerificationError("wechat amount.total must be positive")
        return VerifiedCallback(
            order_no=str(order_no),
            channel_order_no=str(channel_order_no),
            amount_cents=total,
            currency="CNY",
            paid_at=_parse_success_time(plaintext.get("success_time")),
        )

    def build_ack_response(self, *, ok: bool) -> Response:
        # 微信 v3 应答契约：成功 200 {"code":"SUCCESS"}；失败 4xx/5xx {"code":"FAIL"}
        # （渠道收到非 2xx 或 FAIL 会按周期重发通知）。
        if ok:
            return JSONResponse({"code": "SUCCESS", "message": "成功"}, status_code=200)
        return JSONResponse({"code": "FAIL", "message": "失败"}, status_code=400)

    def query_order(self, *, order: Mapping[str, Any]) -> str:
        private_key = self._require_private_key()
        mchid = _config_value(self._settings, "wechat_mchid", "wechat_pay_mchid")
        path = f"/v3/pay/transactions/out-trade-no/{order['order_no']}?mchid={mchid}"
        authorization = _authorization_header(
            private_key=private_key,
            mchid=mchid,
            serial_no=_config_value(
                self._settings, "wechat_mch_serial_no", "wechat_pay_mch_serial_no"
            ),
            method="GET",
            path=path,
            body="",
        )
        try:
            with httpx.Client(transport=self._transport, timeout=_HTTP_TIMEOUT_SECONDS) as client:
                response = client.get(
                    f"{_WECHAT_API_BASE}{path}",
                    headers={
                        "Authorization": authorization,
                        "Accept": "application/json",
                        "Wechatpay-Serial": _config_value(
                            self._settings, "wechat_public_key_id", "wechat_pay_public_key_id"
                        ),
                    },
                )
        except httpx.HTTPError as exc:
            raise ChannelUpstreamError(f"wechat trade query request failed: {exc}") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise ChannelUpstreamError(
                f"wechat trade query rejected: HTTP {response.status_code} "
                f"{_upstream_message(response)}"
            )
        self._verify_response(response)
        try:
            payload = response.json()
            trade_state = payload["trade_state"]
            if not isinstance(trade_state, str) or not trade_state:
                raise TypeError
        except (ValueError, KeyError, TypeError) as exc:
            raise ChannelUpstreamError("wechat trade query returned invalid response") from exc
        return trade_state


def _upstream_message(response: httpx.Response) -> str:
    """微信错误应答 {"code":..., "message":...} 尽力提取；不含敏感信息。"""
    try:
        payload = response.json()
        code = payload.get("code", "")
        message = payload.get("message", "")
        return f"{code} {message}".strip()
    except ValueError:
        return ""
