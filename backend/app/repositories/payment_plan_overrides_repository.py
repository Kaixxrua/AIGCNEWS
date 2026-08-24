from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class PaymentPlanOverride:
    """单个套餐的运行时价格覆盖行；缺行即按 plans.py 默认价生效。"""

    plan_code: str
    amount_cents: int
    updated_at: datetime | None = None


class PaymentPlanOverridesReader(Protocol):
    def list_plan_overrides(self) -> tuple[PaymentPlanOverride, ...]: ...


class PaymentPlanOverridesManager(PaymentPlanOverridesReader, Protocol):
    def upsert_plan_override(self, *, plan_code: str, amount_cents: int) -> PaymentPlanOverride: ...

    def delete_plan_override(self, plan_code: str) -> int: ...


class PaymentPlanOverridesRepository(PaymentPlanOverridesManager, Protocol):
    """Persistence boundary for runtime membership plan price overrides."""
