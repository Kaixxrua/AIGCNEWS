"""支付宝电脑网站支付渠道桩（ADR 0002）。

凭证就绪后接入点（骨架期刻意留空）：
- create_payment：alipay.trade.page.pay 拼跳转表单 URL（RSA2 加签），
  返回 redirect_url 指令；
- verify_and_parse_callback：表单字段 RSA2 验签（支付宝公钥），金额
  total_amount 为元串——必须在本方法内归一到分（×100 取整，拒绝三位小数）。
"""

from __future__ import annotations

from typing import Any, Mapping

from fastapi import Response

from typing import Protocol


class AlipayProviderConfig(Protocol):
    alipay_appid: str
    alipay_private_key_pem: str
    alipay_public_key_pem: str

from backend.app.services.payments.providers.base import (
    PaymentInstruction,
    ProviderNotConfiguredError,
    VerifiedCallback,
)

CHANNEL_ALIPAY_PAGE = "alipay_page"


def _config_value(config: object, *names: str) -> str:
    return next((str(value) for name in names if (value := getattr(config, name, ""))), "")


class AlipayPagePaymentProvider:
    """支付宝电脑网站支付渠道；凭证未齐时全部能力 503。"""

    channel = CHANNEL_ALIPAY_PAGE

    def __init__(self, settings: AlipayProviderConfig) -> None:
        self._settings = settings

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
    ) -> PaymentInstruction:
        # TODO(渠道接入 PR)：alipay.trade.page.pay 跳转 URL → PaymentInstruction("redirect_url", url)
        raise ProviderNotConfiguredError("alipay_page channel credentials pending")

    def verify_and_parse_callback(
        self,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> VerifiedCallback:
        # TODO(渠道接入 PR)：表单验签（sign/sign_type 字段）→ trade_status
        # TRADE_SUCCESS/TRADE_FINISHED 才算支付成功 → 元串归一到分
        raise ProviderNotConfiguredError("alipay_page channel credentials pending")

    def build_ack_response(self, *, ok: bool) -> Response:
        # 支付宝应答契约：纯文本 success/failure（收到 failure 或非 2xx 会重发）。
        return Response(
            content="success" if ok else "failure",
            status_code=200 if ok else 400,
            media_type="text/plain",
        )

    def query_order(self, *, order: Mapping[str, Any]) -> str:
        # TODO(渠道接入 PR)：alipay.trade.query
        raise ProviderNotConfiguredError("alipay_page channel credentials pending")
