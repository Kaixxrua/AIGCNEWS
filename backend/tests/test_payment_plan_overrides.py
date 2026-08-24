"""运行时套餐价格覆盖服务单测（payment_plan_overrides 读路径）。

关键语义：缺行/读异常一律按 plans.py 默认价生效（宁可原价也不 500）；
60s TTL 缓存由写入路径 invalidate 失效；get_effective_plan 与 get_plan
同 fail-closed 语义。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import pytest

from backend.app.services.payments import plan_overrides
from backend.app.services.payments.plan_overrides import (
    configure_plan_overrides_reader,
    get_effective_plan,
    invalidate_plan_overrides_cache,
    resolve_effective_plans,
)
from backend.app.services.payments.plans import MEMBERSHIP_PLANS, UnknownPlanError


@dataclass
class FakePlanOverridesReader:
    amounts: dict[str, int]
    fail: bool = False
    calls: int = 0

    def list_plan_overrides(self):  # noqa: ANN201 - 测试桩保持最小形状
        self.calls += 1
        if self.fail:
            raise RuntimeError("db down")
        from backend.app.repositories.payment_plan_overrides_repository import (
            PaymentPlanOverride,
        )

        return tuple(
            PaymentPlanOverride(plan_code=code, amount_cents=amount)
            for code, amount in self.amounts.items()
        )


@pytest.fixture(autouse=True)
def _reset_plan_overrides_reader():
    configure_plan_overrides_reader(None)
    yield
    configure_plan_overrides_reader(None)


def test_resolve_without_reader_returns_defaults() -> None:
    plans = resolve_effective_plans()
    assert plans["member_monthly"].amount_cents == 1900
    assert plans["member_yearly"].amount_cents == 15900
    assert list(plans) == list(MEMBERSHIP_PLANS)


def test_resolve_merges_reader_overrides() -> None:
    configure_plan_overrides_reader(FakePlanOverridesReader({"member_yearly": 12900}))
    plans = resolve_effective_plans()
    assert plans["member_monthly"].amount_cents == 1900
    assert plans["member_yearly"].amount_cents == 12900


def test_reader_exception_degrades_to_defaults() -> None:
    configure_plan_overrides_reader(FakePlanOverridesReader({"member_yearly": 12900}, fail=True))
    plans = resolve_effective_plans()
    assert plans["member_yearly"].amount_cents == 15900


def test_reader_results_are_cached_within_ttl() -> None:
    reader = FakePlanOverridesReader({"member_monthly": 2500})
    configure_plan_overrides_reader(reader)
    assert resolve_effective_plans()["member_monthly"].amount_cents == 2500
    reader.amounts["member_monthly"] = 3000
    # TTL 内仍读缓存，不二次打 DB
    assert resolve_effective_plans()["member_monthly"].amount_cents == 2500
    assert reader.calls == 1
    invalidate_plan_overrides_cache()
    assert resolve_effective_plans()["member_monthly"].amount_cents == 3000
    assert reader.calls == 2


def test_cache_expires_after_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    reader = FakePlanOverridesReader({"member_monthly": 2500})
    configure_plan_overrides_reader(reader)
    assert resolve_effective_plans()["member_monthly"].amount_cents == 2500
    now = time.monotonic()
    monkeypatch.setattr(time, "monotonic", lambda: now + plan_overrides._CACHE_TTL_SECONDS + 1)
    reader.amounts["member_monthly"] = 3100
    assert resolve_effective_plans()["member_monthly"].amount_cents == 3100


def test_get_effective_plan_is_fail_closed_on_unknown_codes() -> None:
    configure_plan_overrides_reader(FakePlanOverridesReader({"member_monthly": 2500}))
    assert get_effective_plan("member_monthly").amount_cents == 2500
    with pytest.raises(UnknownPlanError):
        get_effective_plan("member_lifetime")
    with pytest.raises(UnknownPlanError):
        get_effective_plan(None)
