"""会员套餐定义：支付收费骨架的商品权威来源（ADR 0002）。

金额一律整数分（杜绝浮点）；时长按日历年月（非 30/365 天），月末钳制
（1 月 31 日 + 1 月 → 2 月 28 日）。前端营销卡 i18n 字面量（'¥19'/'¥129'）
是展示文案，与本文件由两侧测试钉住防漂移；收银台交易面金额只从
GET /api/payments/plans 渲染。
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

from backend.app.services.membership.tiers import MEMBERSHIP_TIER_MEMBER

PLAN_CODE_MEMBER_MONTHLY = "member_monthly"
PLAN_CODE_MEMBER_YEARLY = "member_yearly"


class UnknownPlanError(RuntimeError):
    """未知套餐码：fail-closed，绝不静默映射到任何真实套餐。"""

    def __init__(self, code: object) -> None:
        super().__init__(f"unknown membership plan: {code!r}")
        self.code = code


def _add_calendar_months(base: datetime, months: int) -> datetime:
    """日历年月加法，月末钳制（如 1/31 + 1 月 → 2/28；闰年 2/29）。"""
    month_index = (base.year * 12 + (base.month - 1)) + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    day = min(base.day, calendar.monthrange(year, month)[1])
    return base.replace(year=year, month=month, day=day)


@dataclass(frozen=True)
class MembershipPlan:
    """一个可购买的会员套餐；months 为日历年月数。"""

    code: str
    tier: str
    amount_cents: int
    currency: str
    months: int

    def extend_from(self, base: datetime) -> datetime:
        """从 base 时刻起算的新到期时间（日历年月语义）。"""
        return _add_calendar_months(base, self.months)


MEMBER_MONTHLY = MembershipPlan(
    code=PLAN_CODE_MEMBER_MONTHLY,
    tier=MEMBERSHIP_TIER_MEMBER,
    amount_cents=1900,
    currency="CNY",
    months=1,
)
MEMBER_YEARLY = MembershipPlan(
    code=PLAN_CODE_MEMBER_YEARLY,
    tier=MEMBERSHIP_TIER_MEMBER,
    amount_cents=12900,
    currency="CNY",
    months=12,
)

MEMBERSHIP_PLANS: Mapping[str, MembershipPlan] = {
    plan.code: plan for plan in (MEMBER_MONTHLY, MEMBER_YEARLY)
}


def get_plan(code: object) -> MembershipPlan:
    """按码取套餐；未知码抛 UnknownPlanError（fail-closed）。"""
    plan = MEMBERSHIP_PLANS.get(code) if isinstance(code, str) else None
    if plan is None:
        raise UnknownPlanError(code)
    return plan
