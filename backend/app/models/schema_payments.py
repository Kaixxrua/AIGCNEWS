"""Payment API models, including the safe Ops configuration projection."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

PAYMENT_CHANNELS: frozenset[str] = frozenset({"wechat_native", "alipay_page", "overseas_redirect"})


class PaymentPlanPublic(BaseModel):
    code: str
    tier: str
    amount_cents: int
    currency: str
    months: int


class PaymentChannelPublic(BaseModel):
    channel: str
    available: bool


class PaymentPlansResponse(BaseModel):
    plans: list[PaymentPlanPublic]
    channels: list[PaymentChannelPublic]


class CreatePaymentOrderRequest(BaseModel):
    plan_code: str = Field(min_length=1, max_length=64)
    channel: str = Field(min_length=1, max_length=32)
    idempotency_key: str = Field(default="", max_length=128)


class PaymentInstructionPublic(BaseModel):
    kind: str
    content: str


class PaymentOrderPublic(BaseModel):
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


class PaymentConfigRequest(BaseModel):
    enabled: bool = False
    order_ttl_minutes: int = Field(default=30, ge=5, le=1440)
    public_base_url: str = Field(default="", max_length=1024)
    wechat_appid: str = Field(default="", max_length=256)
    wechat_mchid: str = Field(default="", max_length=128)
    wechat_mch_serial_no: str = Field(default="", max_length=256)
    wechat_api_v3_key: str | None = Field(default=None, max_length=4096)
    wechat_private_key_pem: str | None = Field(default=None, max_length=20000)
    wechat_public_key_id: str = Field(default="", max_length=256)
    wechat_public_key_pem: str | None = Field(default=None, max_length=20000)
    alipay_appid: str = Field(default="", max_length=256)
    alipay_private_key_pem: str | None = Field(default=None, max_length=20000)
    alipay_public_key_pem: str | None = Field(default=None, max_length=20000)
    overseas_provider: str = Field(default="", max_length=32)
    overseas_sandbox: bool = False
    overseas_client_id: str = Field(default="", max_length=256)
    overseas_client_secret: str | None = Field(default=None, max_length=4096)
    overseas_webhook_secret: str | None = Field(default=None, max_length=4096)
    clear_wechat_api_v3_key: bool = False
    clear_wechat_private_key_pem: bool = False
    clear_wechat_public_key_pem: bool = False
    clear_alipay_private_key_pem: bool = False
    clear_alipay_public_key_pem: bool = False
    clear_overseas_client_secret: bool = False
    clear_overseas_webhook_secret: bool = False


class PaymentConfigResponse(BaseModel):
    enabled: bool
    order_ttl_minutes: int
    public_base_url: str
    wechat_appid: str
    wechat_mchid: str
    wechat_mch_serial_no: str
    wechat_public_key_id: str
    alipay_appid: str
    source: str
    updated_at: str | None
    wechat_configured: bool
    alipay_configured: bool
    overseas_configured: bool
    overseas_provider: str
    overseas_sandbox: bool
    overseas_client_id: str
    wechat_api_v3_key_configured: bool
    wechat_api_v3_key_masked: str | None
    wechat_private_key_pem_configured: bool
    wechat_private_key_pem_masked: str | None
    wechat_public_key_pem_configured: bool
    wechat_public_key_pem_masked: str | None
    alipay_private_key_pem_configured: bool
    alipay_private_key_pem_masked: str | None
    alipay_public_key_pem_configured: bool
    alipay_public_key_pem_masked: str | None
    overseas_client_secret_configured: bool
    overseas_client_secret_masked: str | None
    overseas_webhook_secret_configured: bool
    overseas_webhook_secret_masked: str | None


class OpsPaymentPlanEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    tier: str
    currency: str
    months: int
    default_amount_cents: int
    override_amount_cents: int | None
    amount_cents: int
    updated_at: str | None


class OpsPaymentPlansResponse(BaseModel):
    plans: list[OpsPaymentPlanEntry]


class OpsPaymentPlanOverridesRequest(BaseModel):
    """整体聚合语义：null/缺省 = 删除覆盖恢复默认价，整数分 = upsert。"""

    monthly_amount_cents: int | None = None
    yearly_amount_cents: int | None = None
    monthly_usd_amount_cents: int | None = None
    yearly_usd_amount_cents: int | None = None
