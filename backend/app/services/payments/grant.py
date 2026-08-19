"""会员权益发放：回调与 Ops 补单共用的唯一入口（ADR 0002）。

续费叠加语义：
- 生效中 member 且 membership_expires_at 非空 → 在现有到期日上顺延；
- free 或已过期 member → 从现在开始；
- member 且 expires_at IS NULL（长期有效，如历史人工授予）→ 订单仍
  标记 paid 但不顺延（note=permanent_member_noop，ADR 记录的边界）。

恰好一次由仓储层条件 UPDATE 承载（见 postgres_payment_order_repository）：
本函数重复调用（渠道重发/并发回调/重复补单）返回 granted=False 的幂等结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from backend.app.repositories.payment_order_repository import PaymentOrderRepository
from backend.app.repositories.user_account_repository import UserAccountReader
from backend.app.services.membership.tiers import (
    MEMBERSHIP_TIER_MEMBER,
    resolve_effective_tier,
)
from backend.app.services.payments.plans import MembershipPlan
from backend.app.services.payments.providers.base import VerifiedCallback


@dataclass(frozen=True)
class GrantResult:
    """发放结果：granted=False 表示本调用是重放/并发下的幂等 no-op。"""

    granted: bool
    order: dict[str, Any] | None
    new_expires_at: datetime | None
    note: str = ""


def _coerce_now(now: datetime) -> datetime:
    return (
        now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
    )


def compute_grant_expiry(
    *,
    user: Mapping[str, Any],
    plan: MembershipPlan,
    now: datetime,
) -> tuple[datetime | None, str]:
    """续费叠加：返回 (新到期时间, 备注)；None 表示长期有效不再顺延。"""
    current = _coerce_now(now)
    effective = resolve_effective_tier(
        user.get("membership_tier"),
        user.get("membership_expires_at"),
        now=current,
    )
    existing_expires_at = user.get("membership_expires_at")
    if effective == MEMBERSHIP_TIER_MEMBER and existing_expires_at is None:
        # 长期有效会员（人工授予历史形态）：不再顺延
        return None, "permanent_member_noop"
    base = current
    if effective == MEMBERSHIP_TIER_MEMBER and isinstance(
        existing_expires_at, datetime
    ):
        base = existing_expires_at
        if base.tzinfo is None:
            base = base.replace(tzinfo=timezone.utc)
        if base <= current:
            base = current
    return plan.extend_from(base), ""


def mark_paid_and_grant(
    *,
    orders: PaymentOrderRepository,
    users: UserAccountReader,
    order: Mapping[str, Any],
    verified: VerifiedCallback,
    plan: MembershipPlan,
    now: datetime,
    callback_payload: str = "",
) -> GrantResult:
    """标记订单已支付并发放会员权益；重复调用幂等（granted=False）。"""
    current = _coerce_now(now)
    user = users.get_user_by_id(int(order["user_id"]))
    if user is None:
        # 用户已注销（FK ON DELETE CASCADE 下订单通常也随之消失；防御脏数据）
        return GrantResult(granted=False, order=None, new_expires_at=None, note="user_missing")

    new_expires_at, note = compute_grant_expiry(user=user, plan=plan, now=current)
    updated = orders.mark_paid_and_grant(
        order_id=int(order["id"]),
        channel_order_no=verified.channel_order_no,
        paid_at=verified.paid_at,
        callback_payload=callback_payload,
        grant_expires_at=new_expires_at,
        user_id=int(order["user_id"]),
        new_membership_tier=plan.tier,
        new_membership_expires_at=new_expires_at,
    )
    if updated is None:
        # 重放/并发：条件更新 rowcount=0，零写入
        return GrantResult(granted=False, order=None, new_expires_at=None, note="already_processed")
    return GrantResult(
        granted=True,
        order=updated,
        new_expires_at=new_expires_at,
        note=note,
    )
