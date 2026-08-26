"""Admin projection and update semantics for runtime membership plan pricing."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from backend.app.repositories.payment_plan_overrides_repository import (
    PaymentPlanOverride,
    PaymentPlanOverridesManager,
)
from backend.app.services.payments.plan_overrides import invalidate_plan_overrides_cache
from backend.app.services.payments.plans import (
    MEMBERSHIP_PLANS,
    PLAN_CODE_MEMBER_MONTHLY,
    PLAN_CODE_MEMBER_MONTHLY_USD,
    PLAN_CODE_MEMBER_YEARLY,
    PLAN_CODE_MEMBER_YEARLY_USD,
    effective_plans,
)

_MIN_AMOUNT_CENTS = 100
_MAX_AMOUNT_CENTS = 1000000
# PUT 整体聚合语义：显式四字段（套餐目录被 test_payment_plans.py 钉为四个），
# null/缺省 = 删除覆盖恢复默认价，整数 = upsert 覆盖。
_REQUEST_FIELDS: Mapping[str, str] = {
    "monthly_amount_cents": PLAN_CODE_MEMBER_MONTHLY,
    "yearly_amount_cents": PLAN_CODE_MEMBER_YEARLY,
    "monthly_usd_amount_cents": PLAN_CODE_MEMBER_MONTHLY_USD,
    "yearly_usd_amount_cents": PLAN_CODE_MEMBER_YEARLY_USD,
}


@dataclass(frozen=True)
class PaymentPlanPricingEntry:
    code: str
    tier: str
    currency: str
    months: int
    default_amount_cents: int
    override_amount_cents: int | None
    amount_cents: int
    updated_at: str | None


class PaymentPlanOverridesAdminService:
    def __init__(self, repository: PaymentPlanOverridesManager) -> None:
        self._repository = repository

    async def list_plans(self) -> list[PaymentPlanPricingEntry]:
        rows = await asyncio.to_thread(self._repository.list_plan_overrides)
        return self._to_projection({row.plan_code: row for row in rows})

    async def update_plans(self, values: Mapping[str, Any]) -> list[PaymentPlanPricingEntry]:
        for field, code in _REQUEST_FIELDS.items():
            amount = values.get(field)
            if amount is None:
                await asyncio.to_thread(self._repository.delete_plan_override, code)
                continue
            cents = int(amount)
            if not _MIN_AMOUNT_CENTS <= cents <= _MAX_AMOUNT_CENTS:
                raise ValueError("套餐价格必须是 100-1000000 之间的整数分")
            await asyncio.to_thread(
                self._repository.upsert_plan_override, plan_code=code, amount_cents=cents
            )
        invalidate_plan_overrides_cache()
        rows = await asyncio.to_thread(self._repository.list_plan_overrides)
        return self._to_projection({row.plan_code: row for row in rows})

    @staticmethod
    def _to_projection(overrides: Mapping[str, PaymentPlanOverride]) -> list[PaymentPlanPricingEntry]:
        merged = effective_plans({code: row.amount_cents for code, row in overrides.items()})
        return [
            PaymentPlanPricingEntry(
                code=plan.code,
                tier=plan.tier,
                currency=plan.currency,
                months=plan.months,
                default_amount_cents=MEMBERSHIP_PLANS[plan.code].amount_cents,
                override_amount_cents=overrides[plan.code].amount_cents if plan.code in overrides else None,
                amount_cents=merged[plan.code].amount_cents,
                updated_at=overrides[plan.code].updated_at.isoformat()
                if plan.code in overrides and overrides[plan.code].updated_at
                else None,
            )
            for plan in MEMBERSHIP_PLANS.values()
        ]
