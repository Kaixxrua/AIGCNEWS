"""微信支付 Native 扫码渠道桩（ADR 0002）。

凭证就绪后接入点（骨架期刻意留空）：
- create_payment：微信 v3 Native 下单（POST /v3/pay/transactions/native），
  返回 code_url 作为 qr_code 指令；
- verify_and_parse_callback：按 Wechatpay-Signature/Serial/Timestamp/Nonce
  头对 raw_body 原始字节验签（平台证书或公钥模式），校验 ±5 分钟时间戳
  防重放，AES-GCM 解密 resource 后取 out_trade_no/transaction_id/amount.total。
"""

from __future__ import annotations

from typing import Any, Mapping

from fastapi import Response
from fastapi.responses import JSONResponse

from typing import Protocol


class WeChatProviderConfig(Protocol):
    wechat_appid: str
    wechat_mchid: str
    wechat_mch_serial_no: str
    wechat_api_v3_key: str
    wechat_private_key_pem: str

from backend.app.services.payments.providers.base import (
    PaymentInstruction,
    ProviderNotConfiguredError,
    VerifiedCallback,
)

CHANNEL_WECHAT_NATIVE = "wechat_native"


def _config_value(config: object, *names: str) -> str:
    return next((str(value) for name in names if (value := getattr(config, name, ""))), "")


class WeChatNativePaymentProvider:
    """WeChat Pay v3 Native（扫码）渠道；凭证未齐时全部能力 503。"""

    channel = CHANNEL_WECHAT_NATIVE

    def __init__(self, settings: WeChatProviderConfig) -> None:
        self._settings = settings

    def is_configured(self) -> bool:
        return all(
            [
                _config_value(self._settings, "wechat_appid", "wechat_pay_appid"),
                _config_value(self._settings, "wechat_mchid", "wechat_pay_mchid"),
                _config_value(self._settings, "wechat_mch_serial_no", "wechat_pay_mch_serial_no"),
                _config_value(self._settings, "wechat_api_v3_key", "wechat_pay_api_v3_key"),
                _config_value(self._settings, "wechat_private_key_pem", "wechat_pay_private_key_path"),
            ]
        )

    def create_payment(
        self,
        *,
        order: Mapping[str, Any],
        notify_url: str,
        return_url: str | None,
    ) -> PaymentInstruction:
        # TODO(渠道接入 PR)：v3 Native 下单，code_url → PaymentInstruction("qr_code", url)
        raise ProviderNotConfiguredError("wechat_native channel credentials pending")

    def verify_and_parse_callback(
        self,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> VerifiedCallback:
        # TODO(渠道接入 PR)：平台证书验签（原始字节）→ 防重放窗口 → 解密 resource
        raise ProviderNotConfiguredError("wechat_native channel credentials pending")

    def build_ack_response(self, *, ok: bool) -> Response:
        # 微信 v3 应答契约：成功 200 {"code":"SUCCESS"}；失败 4xx/5xx {"code":"FAIL"}
        # （渠道收到非 2xx 或 FAIL 会按周期重发通知）。
        if ok:
            return JSONResponse({"code": "SUCCESS", "message": "成功"}, status_code=200)
        return JSONResponse({"code": "FAIL", "message": "失败"}, status_code=400)

    def query_order(self, *, order: Mapping[str, Any]) -> str:
        # TODO(渠道接入 PR)：GET /v3/pay/transactions/out-trade-no/{order_no}
        raise ProviderNotConfiguredError("wechat_native channel credentials pending")
