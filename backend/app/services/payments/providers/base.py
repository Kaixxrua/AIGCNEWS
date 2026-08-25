"""支付渠道抽象（ADR 0002）。

骨架期三渠道（微信 Native / 支付宝电脑网站 / 海外跳转）以"未配置即不可用"
的桩落地：凭证就位后只需填充 create_payment 与 verify_and_parse_callback
两个方法体，路由/状态机/发权益链路不变。海外跳转是单槽渠道
（overseas_redirect），由 registry 按 overseas_provider 分发到具体
服务商实现（paypal / pingpong），未选服务商时落 fail-closed 桩。

验签三条不可妥协的纪律（刻进接口契约，渠道接入 PR 必须遵守）：
1. 验签必须作用于 raw_body 原始字节，禁止先 JSON parse 再验
   （微信 v3 / PingPong 均对原始报文串签名）；
2. 渠道时间戳/nonce 防重放窗口在 provider 内部检查（微信 v3 ±5 分钟），
   通过后才返回 VerifiedCallback；
3. 金额由 provider 归一到"分"（支付宝报文是元串、海外渠道是金额串），
   路由层不做单位换算。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Protocol

from fastapi import Response


@dataclass(frozen=True)
class PaymentInstruction:
    """下单成功返回给前端的支付指令。"""

    kind: str  # "qr_code" | "redirect_url"
    content: str  # 微信 code_url / 支付宝、海外渠道的跳转 URL


@dataclass(frozen=True)
class VerifiedCallback:
    """验签通过后的渠道异步通知（金额已归一到分）。"""

    order_no: str  # 本站业务单号（渠道回传）
    channel_order_no: str  # 渠道交易号
    amount_cents: int
    currency: str
    paid_at: datetime


class CallbackVerificationError(RuntimeError):
    """验签失败/报文不合法：路由映射 400 + 失败 ACK，零状态变更。"""


class ProviderNotConfiguredError(RuntimeError):
    """渠道凭证未配置：路由映射 503 payment_channel_not_configured。"""


class ChannelUpstreamError(RuntimeError):
    """渠道远端调用失败（网络错误或非 2xx）：路由映射 502
    payment_channel_upstream_error。与未配置区分——这表示渠道侧已受理
    交互但调用失败，订单已落库，前端提示重试而非「未配置」。"""


class PaymentProvider(Protocol):
    """一个支付渠道的骨架接口。"""

    channel: str

    def is_configured(self) -> bool:
        """所需凭证全部就绪才为 True；否则下单/回调对该渠道 503。"""
        ...

    def create_payment(
        self,
        *,
        order: Mapping[str, Any],
        notify_url: str,
        return_url: str | None,
        shopper_ip: str | None = None,
    ) -> PaymentInstruction:
        """向渠道下单，返回支付指令；未配置抛 ProviderNotConfiguredError。

        shopper_ip 为可信代理口径的下单人 IP（PingPong 等渠道必填），
        不需要的渠道忽略之。
        """
        ...

    def verify_and_parse_callback(
        self,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
    ) -> VerifiedCallback | None:
        """验签并解析渠道异步通知；验签失败抛 CallbackVerificationError，
        未配置抛 ProviderNotConfiguredError。

        返回 None 表示「验签通过但非终态事件」（如 PayPal 已自动 capture 的
        CHECKOUT.ORDER.APPROVED、PingPong 的非 SUCCESS 状态通知）：路由直接
        build_ack_response(ok=True) 终止渠道重发，零状态变更。
        """
        ...

    def build_ack_response(self, *, ok: bool) -> Response:
        """渠道约定的应答报文（形状错了渠道会无限重发；本方法不依赖凭证，
        骨架期即完整实现并钉契约）。"""
        ...

    def query_order(self, *, order: Mapping[str, Any]) -> str:
        """主动查单（关单前对账用）；骨架期不进路由，抛
        ProviderNotConfiguredError，供渠道接入 PR 消费。"""
        ...
