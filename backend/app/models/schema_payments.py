"""支付收费骨架的 API 模型（ADR 0002）。

金额一律整数分；callback_payload 是审计列，永不出现在任何响应模型里。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

PAYMENT_CHANNELS: frozenset[str] = frozenset(
    {"wechat_native", "alipay_page", "stripe"}
)


class PaymentPlanPublic(BaseModel):
    """套餐的公开描述；金额/时长权威来源是后端 plans.py 常量。"""

    code: str
    tier: str
    amount_cents: int
    currency: str
    months: int


class PaymentChannelPublic(BaseModel):
    """渠道可用性：available=False 时收银台置灰（凭证未配置）。"""

    channel: str
    available: bool


class PaymentPlansResponse(BaseModel):
    plans: list[PaymentPlanPublic]
    channels: list[PaymentChannelPublic]


class CreatePaymentOrderRequest(BaseModel):
    plan_code: str = Field(min_length=1, max_length=64)
    channel: str = Field(min_length=1, max_length=32)
    # 客户端生成的幂等键：重复提交（双击/重试/刷新）返回既有订单
    idempotency_key: str = Field(default="", max_length=128)


class PaymentInstructionPublic(BaseModel):
    kind: str  # "qr_code" | "redirect_url" | "client_secret"
    content: str


class PaymentOrderPublic(BaseModel):
    """用户侧订单视图；永不含 callback_payload（审计列仅 Ops 可见）。"""

    order_no: str
    plan_code: str
    channel: str
    amount_cents: int
    currency: str
    status: str
    channel_order_no: str = ""
    expires_at: datetime
    paid_at: datetime | None = None
    created_at: datetime


class CreatePaymentOrderResponse(BaseModel):
    order: PaymentOrderPublic
    instruction: PaymentInstructionPublic


class PaymentOrderListResponse(BaseModel):
    items: list[PaymentOrderPublic]
    total: int
    page: int
    page_size: int
