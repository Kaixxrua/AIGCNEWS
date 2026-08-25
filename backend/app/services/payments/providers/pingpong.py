"""PingPongCheckout v4 收单渠道（overseas_redirect 的服务商实现之一）。

契约取自官方 v4 文档（实现时逐页核对，无沙箱实测，见 docs/payments.md）：
- 端点：POST {base}/v4/payment/prePay（Hosted 跳转收银台）、
  POST {base}/v4/payment/query；沙箱 base =
  sandbox-acquirer-payment.pingpongx.com，生产默认 FRA 站
  acquirer-payment.pingpongx.com（SG/US 站需换各自域名，凭证开通后按
  商户实体注册地调整）。
- 报文：公共参数 accId/clientId/signType/version + bizContent（JSON
  字符串），sign 外全部字段按键 ASCII 升序拼 ``key=value&...``、盐置首，
  SHA256（推荐，本实现固定）/MD5 大写 hex。请求、同步应答、异步通知同规则。
- 回调：验签对齐官方 PHP 参考实现（原始文本先做 ``\\n`` 等转义归一再
  JSON 解析）；钉死 clientId/accId 归属；code == "000000" 且
  bizContent.status == "SUCCESS" 才产出 VerifiedCallback（金额串
  fail-closed 归一到分）；其余状态/非 RECHARGE 通知一律返回 None——
  验签通过但非终态，路由 ACK 200 终止重发，零状态变更。
- ACK 契约：HTTP 200 纯文本 ``OK`` 即成功（官方：2xx 且报文非 FAIL）；
  失败 400 + ``FAIL``（触发 5s/5s/3m/10m/... 递增重发）。

通用凭证槽在本服务商下的语义（配置面板/文档的「海外支付」区）：
- overseas_client_id      → clientId（商户号）
- overseas_client_secret  → 签名盐 salt（请求加签与回调验签共用）
- overseas_webhook_secret → accId（门店号，请求公共参数 + 回调归属校验）
- overseas_sandbox        → 切沙箱域名
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Protocol
from urllib.parse import urlencode

import httpx
from fastapi import Response

from backend.app.services.payments.providers.base import (
    CallbackVerificationError,
    ChannelUpstreamError,
    PaymentInstruction,
    ProviderNotConfiguredError,
    VerifiedCallback,
)
from backend.app.services.payments.providers.overseas_redirect import (
    CHANNEL_OVERSEAS_REDIRECT,
)

logger = logging.getLogger(__name__)


class PingPongProviderConfig(Protocol):
    overseas_provider: str
    overseas_sandbox: bool
    overseas_client_id: str
    overseas_client_secret: str
    overseas_webhook_secret: str
    public_base_url: str


_SANDBOX_API_BASE = "https://sandbox-acquirer-payment.pingpongx.com"
_LIVE_API_BASE = "https://acquirer-payment.pingpongx.com"  # FRA 站（其他区域商户兜底）
_PREPAY_PATH = "/v4/payment/prePay"
_QUERY_PATH = "/v4/payment/query"
_HTTP_TIMEOUT_SECONDS = 10.0
_SIGN_TYPE = "SHA256"
_API_VERSION = "1.0"
_CODE_SUCCESS = "000000"
_NOTIFY_TYPE_PAYMENT = "RECHARGE"
_STATUS_SUCCESS = "SUCCESS"
_DEFAULT_GOODS_IMAGE_URL = "https://aigcnews.cn/logo.png"


def _product_name(order: Mapping[str, Any]) -> str:
    # 官方风控建议业务参数避免括号等特殊字符（< > 会硬拦截），与
    # 微信/支付宝/PayPal 的渠道内命名区分：本渠道用连字符形态。
    if str(order.get("plan_code", "")).endswith("yearly"):
        return "AIGC Radar Membership - Yearly"
    return "AIGC Radar Membership - Monthly"


def _amount_str(amount_cents: object) -> str:
    """分 → PingPong 金额串（两位小数；与支付宝渠道的币种小数位假设一致）。"""
    try:
        cents = int(amount_cents)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid payment amount") from exc
    if cents <= 0:
        raise ValueError("payment amount must be positive")
    return f"{Decimal(cents) / Decimal(100):.2f}"


def _amount_to_cents(value: object) -> int:
    """通知金额串 fail-closed 归一到分（官方示例带 6 位小数，按可整除校验）。"""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CallbackVerificationError("invalid pingpong amount") from exc
    if not amount.is_finite() or amount <= 0:
        raise CallbackVerificationError("pingpong amount must be positive")
    cents = amount * 100
    if cents != cents.to_integral_value():
        raise CallbackVerificationError("pingpong amount is not representable in cents")
    return int(cents)


def _digest(content: str, sign_type: str) -> str:
    """signContent（盐已置首）→ 大写 hex；算法仅认官方两种。"""
    if sign_type == "SHA256":
        return hashlib.sha256(content.encode("utf-8")).hexdigest().upper()
    if sign_type == "MD5":
        # 渠道契约保留 MD5 兼容（商户后台可配），新接入固定 SHA256。
        return hashlib.md5(content.encode("utf-8")).hexdigest().upper()  # noqa: S324
    raise CallbackVerificationError(f"unsupported pingpong signType: {sign_type}")


def _sign_content(fields: Mapping[str, str], *, salt: str, sign_type: str) -> str:
    """盐置首 + 键 ASCII 升序 key=value&...（官方签名串装配规则）。

    防御性剔除 sign 字段（官方规则：sign 不参与签名）——正常调用方传入的
    映射本就不含 sign，这里兜底防误传。
    """
    return _digest(
        salt + "&".join(f"{key}={fields[key]}" for key in sorted(fields) if key != "sign"),
        sign_type,
    )


def _normalize_callback_text(raw_body: bytes) -> str:
    """对齐官方 PHP 验签参考实现的原始报文转义归一。

    官方验签代码在 JSON 解析前把原始文本中的 ``\\n``/``\\r``/``\\f``/
    ``\\t``/``\\v`` 替换为双反斜杠形态、``\\\\"`` 替换为 ``\\\\\\"``，
    使 issuerResultMsg 等字段内的转义序列按渠道加签时的字面形态参与验签。
    """
    text = raw_body.decode("utf-8")
    for escape in ("\\n", "\\r", "\\f", "\\t", "\\v"):
        text = text.replace(escape, "\\" + escape)
    return text.replace('\\\\"', '\\\\\\"')


def _parse_epoch_ms(value: object) -> datetime:
    """Unix 毫秒（官方报文中数字/字符串形态均有）→ UTC datetime。"""
    try:
        millis = int(str(value))
    except (TypeError, ValueError) as exc:
        raise CallbackVerificationError("invalid pingpong transaction time") from exc
    if millis <= 0:
        raise CallbackVerificationError("invalid pingpong transaction time")
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)


class PingPongProvider:
    """PingPongCheckout v4 Hosted 跳转渠道；凭证未齐时全部能力 503。"""

    channel = CHANNEL_OVERSEAS_REDIRECT

    def __init__(
        self,
        settings: PingPongProviderConfig,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client_id = str(getattr(settings, "overseas_client_id", "") or "")
        self._salt = str(getattr(settings, "overseas_client_secret", "") or "")
        self._acc_id = str(getattr(settings, "overseas_webhook_secret", "") or "")
        self._sandbox = bool(getattr(settings, "overseas_sandbox", False))
        self._public_base_url = str(getattr(settings, "public_base_url", "") or "")
        self._transport = transport

    def is_configured(self) -> bool:
        return all([self._client_id, self._salt, self._acc_id])

    def _api_base(self) -> str:
        return _SANDBOX_API_BASE if self._sandbox else _LIVE_API_BASE

    def _signed_envelope(self, biz: Mapping[str, Any]) -> dict[str, str]:
        envelope = {
            "accId": self._acc_id,
            "clientId": self._client_id,
            "signType": _SIGN_TYPE,
            "version": _API_VERSION,
            "bizContent": json.dumps(biz, ensure_ascii=False, separators=(",", ":")),
        }
        envelope["sign"] = _sign_content(envelope, salt=self._salt, sign_type=_SIGN_TYPE)
        return envelope

    def _post(self, path: str, biz: Mapping[str, Any]) -> dict[str, Any]:
        """加签调用并返回解析后的 bizContent；同步应答带 sign 时验签。"""
        envelope = self._signed_envelope(biz)
        try:
            with httpx.Client(transport=self._transport, timeout=_HTTP_TIMEOUT_SECONDS) as client:
                response = client.post(
                    f"{self._api_base()}{path}",
                    content=json.dumps(envelope, ensure_ascii=False).encode("utf-8"),
                    headers={"Content-Type": "application/json", "Accept": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise ChannelUpstreamError(f"pingpong api request failed: {exc}") from exc
        if response.status_code < 200 or response.status_code >= 300:
            raise ChannelUpstreamError(
                f"pingpong api rejected: HTTP {response.status_code}"
            )
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError
        except (ValueError, TypeError) as exc:
            raise ChannelUpstreamError("pingpong api returned non-JSON body") from exc
        self._verify_response_signature(payload)
        code = payload.get("code")
        if code != _CODE_SUCCESS:
            raise ChannelUpstreamError(
                f"pingpong api rejected: {code} {payload.get('description', '')}".strip()
            )
        biz_content = payload.get("bizContent")
        if not isinstance(biz_content, str) or not biz_content:
            raise ChannelUpstreamError("pingpong api returned empty bizContent")
        try:
            parsed = json.loads(biz_content)
            if not isinstance(parsed, dict):
                raise TypeError
        except (ValueError, TypeError) as exc:
            raise ChannelUpstreamError("pingpong api returned invalid bizContent") from exc
        return parsed

    def _verify_response_signature(self, payload: Mapping[str, Any]) -> None:
        """同步应答验签：带 sign 必验（篡改即拒）；缺 sign 告警放行。

        官方声明应答全量加签，但无沙箱实测期对「错误应答是否带 sign」保留
        容错——缺失只告警（code 非 000000 仍会抛错），不匹配则一律拒绝。
        """
        sign = payload.get("sign")
        if not sign:
            logger.warning("[Payments] pingpong response missing sign field")
            return
        sign_type = payload.get("signType")
        if sign_type not in ("MD5", "SHA256"):
            raise ChannelUpstreamError("pingpong response has unsupported signType")
        fields: dict[str, str] = {}
        for key, value in payload.items():
            if key == "sign":
                continue
            if not isinstance(value, str):
                raise ChannelUpstreamError("pingpong response contains non-string field")
            fields[key] = value
        expected = _sign_content(fields, salt=self._salt, sign_type=sign_type)
        if not hmac.compare_digest(expected, str(sign).upper()):
            raise ChannelUpstreamError("pingpong response signature mismatch")

    def create_payment(
        self,
        *,
        order: Mapping[str, Any],
        notify_url: str,
        return_url: str | None,
        shopper_ip: str | None = None,
    ) -> PaymentInstruction:
        if not self.is_configured():
            raise ProviderNotConfiguredError("overseas_redirect(pingpong) channel not configured")
        shopper_ipv4 = (shopper_ip or "").strip()
        try:
            address = ipaddress.ip_address(shopper_ipv4)
        except ValueError as exc:
            # shopperIP 为官方必填且限 IPv4；本地解析不出可信 IP 属上游前
            # 置条件失败，映射 502 提示重试而非静默放行到渠道被拒。
            raise ChannelUpstreamError("pingpong prePay requires a valid shopper ipv4") from exc
        if address.version != 4:
            raise ChannelUpstreamError("pingpong prePay requires a valid shopper ipv4")

        order_no = str(order["order_no"])
        amount = _amount_str(order["amount_cents"])
        result_url = self._result_url(order, return_url) or notify_url
        goods: dict[str, str] = {
            "name": _product_name(order),
            "unitPrice": amount,
            "number": "1",
            "imgUrl": self._goods_image_url(),
            "virtualProduct": "Y",
            "itemType": "1",  # DIGITAL
        }
        biz: dict[str, Any] = {
            "captureDelayHours": 0,  # 立即捕获（手动捕获走 -1 + capture API，会员场景不需要）
            "amount": amount,
            "currency": str(order["currency"]).upper(),
            # merchantTransactionId = order_no：官方约定同单号参数不可变更，天然幂等。
            "merchantTransactionId": order_no,
            "payResultUrl": result_url,
            "payCancelUrl": result_url,
            "notificationUrl": notify_url,
            "shopperIP": shopper_ipv4,
            "goods": [goods],
        }
        expires_at = order.get("expires_at")
        if isinstance(expires_at, datetime):
            # 对齐本站订单 TTL（官方窗口 3 分钟~10 天，渠道侧到点自关）。
            biz["timeExpire"] = str(int(expires_at.timestamp()))
        parsed = self._post(_PREPAY_PATH, biz)
        payment_url = parsed.get("paymentUrl")
        if not isinstance(payment_url, str) or not payment_url:
            raise ChannelUpstreamError("pingpong prePay returned no paymentUrl")
        return PaymentInstruction(kind="redirect_url", content=payment_url)

    def _result_url(self, order: Mapping[str, Any], return_url: str | None) -> str:
        """payResultUrl/payCancelUrl 同形：回跳收银台带 order_no+plan 供续单。"""
        if not return_url:
            return ""
        order_no = str(order["order_no"])
        plan = "yearly" if str(order.get("plan_code", "")).endswith("yearly") else "monthly"
        separator = "&" if "?" in return_url else "?"
        return f"{return_url}{separator}{urlencode({'order_no': order_no, 'plan': plan})}"

    def _goods_image_url(self) -> str:
        base = self._public_base_url.strip().rstrip("/")
        return f"{base}/logo.png" if base else _DEFAULT_GOODS_IMAGE_URL

    def verify_and_parse_callback(
        self,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> VerifiedCallback | None:
        del headers  # PingPong 通知签名在报文体内，无特殊头
        if not self.is_configured():
            raise ProviderNotConfiguredError("overseas_redirect(pingpong) channel not configured")
        try:
            payload = json.loads(_normalize_callback_text(raw_body))
            if not isinstance(payload, dict):
                raise TypeError
        except (ValueError, TypeError, UnicodeDecodeError) as exc:
            raise CallbackVerificationError("invalid pingpong callback body") from exc
        self._verify_callback_signature(payload)
        # 归属钉死：商户号/门店号必须等于配置，防跨商户通知重放。
        if payload.get("clientId") != self._client_id or payload.get("accId") != self._acc_id:
            raise CallbackVerificationError("pingpong callback identity mismatch")
        if str(payload.get("code", "")) != _CODE_SUCCESS:
            return None  # 非成功报文：验签通过但非终态，ACK 终止重发
        biz_raw = payload.get("bizContent")
        if not isinstance(biz_raw, str) or not biz_raw:
            raise CallbackVerificationError("pingpong callback missing bizContent")
        try:
            biz = json.loads(biz_raw)
            if not isinstance(biz, dict):
                raise TypeError
        except (ValueError, TypeError) as exc:
            raise CallbackVerificationError("invalid pingpong bizContent") from exc
        if biz.get("notifyType") != _NOTIFY_TYPE_PAYMENT:
            return None  # 非支付结果通知（本渠道只订 RECHARGE）
        if biz.get("status") != _STATUS_SUCCESS:
            return None  # FAILED/CANCEL/AUTH_SUCCESS 等：零状态变更，关单由到期任务负责
        order_no = biz.get("merchantTransactionId")
        channel_order_no = biz.get("transactionId")
        if (
            not isinstance(order_no, str)
            or not order_no
            or not isinstance(channel_order_no, str)
            or not channel_order_no
        ):
            raise CallbackVerificationError("pingpong callback missing order identifiers")
        currency = biz.get("currency")
        if not isinstance(currency, str) or not currency:
            raise CallbackVerificationError("pingpong callback missing currency")
        paid_at_raw = biz.get("transactionEndTime") or biz.get("transactionTime")
        return VerifiedCallback(
            order_no=order_no,
            channel_order_no=channel_order_no,
            amount_cents=_amount_to_cents(biz.get("amount")),
            currency=currency.upper(),
            paid_at=_parse_epoch_ms(paid_at_raw),
        )

    def _verify_callback_signature(self, payload: Mapping[str, Any]) -> None:
        sign = payload.get("sign")
        sign_type = payload.get("signType")
        if not isinstance(sign, str) or not sign or sign_type not in ("MD5", "SHA256"):
            raise CallbackVerificationError("missing pingpong callback signature")
        fields: dict[str, str] = {}
        for key, value in payload.items():
            if key == "sign":
                continue
            # 官方通知顶层字段全为字符串（bizContent 整体是 JSON 字符串）；
            # 出现非字符串即与契约不符，fail-closed。
            if not isinstance(value, str):
                raise CallbackVerificationError("pingpong callback field is not a string")
            fields[key] = value
        expected = _sign_content(fields, salt=self._salt, sign_type=sign_type)
        if not hmac.compare_digest(expected, sign.upper()):
            raise CallbackVerificationError("pingpong callback signature mismatch")

    def build_ack_response(self, *, ok: bool) -> Response:
        # PingPong 应答契约：2xx 且报文非 FAIL 即成功（报文内容无强制），
        # 失败用非 2xx + FAIL 双信号，避免渠道按 5s/5s/3m/... 节奏无限重发。
        return Response(
            content="OK" if ok else "FAIL",
            status_code=200 if ok else 400,
            media_type="text/plain",
        )

    def query_order(self, *, order: Mapping[str, Any]) -> str:
        if not self.is_configured():
            raise ProviderNotConfiguredError("overseas_redirect(pingpong) channel not configured")
        parsed = self._post(_QUERY_PATH, {"merchantTransactionId": str(order["order_no"])})
        status_value = parsed.get("status")
        if not isinstance(status_value, str) or not status_value:
            raise ChannelUpstreamError("pingpong query returned no status")
        return status_value
