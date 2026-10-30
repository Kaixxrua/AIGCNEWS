"""ShinyDesk 商品与运行配置。

商品是单一固定价（$9.99 一次性，永久码），不进 payments/plans.py 的会员目录、
不受 payment_plan_overrides 调价影响；授权服务器侧对价格与商品码再校验一次。
配置只读环境变量（密钥只读文件路径），缺任何一项即「不可购买」。
"""

from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

PRODUCT_CODE = "shinydesk_standard_usd"
LICENSE_PRODUCT = "shinydesk-standard"  # 授权服务器 purchases.cjs 的商品码
AMOUNT_CENTS = 999
CURRENCY = "USD"
ITEM_NAME = "ShinyDesk license - lifetime, 1 PC + 1 Android phone"
BRAND_NAME = "ShinyDesk"
ORDER_NO_PREFIX = "SD"
_ORDER_NO_RE = re.compile(r"SD\d{14}[A-F0-9]{8}\Z")

DEFAULT_SITE_URL = "https://aigcnews.cn/api/shiny-downloads/"


def generate_order_no() -> str:
    """SD + UTC 时间戳 + 8 位随机十六进制（授权服务器校验 ^SD\\d{14}[A-F0-9]{6,12}$）。"""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{ORDER_NO_PREFIX}{stamp}{secrets.token_hex(4).upper()}"


def is_shinydesk_order_no(value: object) -> bool:
    return isinstance(value, str) and bool(_ORDER_NO_RE.fullmatch(value))


def checkout_order_mapping(row: Mapping[str, object]) -> dict[str, object]:
    """PayPalProvider.create_payment 用的订单映射（覆盖商品名/品牌/回跳参数）。"""
    return {
        "order_no": row["order_no"],
        "plan_code": PRODUCT_CODE,
        "amount_cents": row["amount_cents"],
        "currency": row["currency"],
        "item_name": ITEM_NAME,
        "brand_name": BRAND_NAME,
        "return_order_only": True,
        "digital_goods": True,
    }


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ShinyDeskConfig:
    enabled: bool
    site_url: str
    license_api_base: str
    license_key_id: str
    license_key_file: str

    @property
    def license_configured(self) -> bool:
        return bool(self.license_api_base and self.license_key_file)


def load_config(env: Mapping[str, str] | None = None) -> ShinyDeskConfig:
    """环境变量：
    SHINYDESK_CHECKOUT_ENABLED   总开关（默认关，关闭时 /api/shinydesk/* 404）
    SHINYDESK_SITE_URL           PayPal 回跳页（默认线上下载页）
    SHINYDESK_LICENSE_API_BASE   授权服务器基址，如 https://aigcnews.cn/shiny-service
    SHINYDESK_LICENSE_KEY_ID     HMAC 密钥 id（与授权服务器 SHINY_PURCHASE_KEY_ID 一致）
    SHINYDESK_LICENSE_HMAC_KEY_FILE  HMAC 密钥文件路径（≥32 字节，只读挂载）
    """
    source = os.environ if env is None else env
    return ShinyDeskConfig(
        enabled=_flag(source.get("SHINYDESK_CHECKOUT_ENABLED")),
        site_url=(source.get("SHINYDESK_SITE_URL") or DEFAULT_SITE_URL).strip(),
        license_api_base=(source.get("SHINYDESK_LICENSE_API_BASE") or "").strip().rstrip("/"),
        license_key_id=(source.get("SHINYDESK_LICENSE_KEY_ID") or "aigcnews").strip(),
        license_key_file=(source.get("SHINYDESK_LICENSE_HMAC_KEY_FILE") or "").strip(),
    )
