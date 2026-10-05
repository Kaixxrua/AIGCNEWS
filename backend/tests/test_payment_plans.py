"""套餐与日历年月续约语义单测（支付骨架 PR-2）。

金额/时长是商业承诺：1900 分月付、15900 分年付由本文件钉死，任何漂移
必须改测试。月末钳制与日历年月语义是续约计算的核心正确性来源。
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.services.payments.plans import (
    CHANNEL_CURRENCIES,
    MEMBER_MONTHLY,
    MEMBER_MONTHLY_USD,
    MEMBER_YEARLY,
    MEMBER_YEARLY_USD,
    MEMBERSHIP_PLANS,
    UnknownPlanError,
    effective_plans,
    get_plan,
)


def _dt(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, 0, tzinfo=timezone.utc)


def test_plan_amounts_are_pinned_in_cents() -> None:
    assert MEMBER_MONTHLY.code == "member_monthly"
    assert MEMBER_MONTHLY.amount_cents == 1900
    assert MEMBER_MONTHLY.currency == "CNY"
    assert MEMBER_MONTHLY.months == 1
    assert MEMBER_YEARLY.code == "member_yearly"
    assert MEMBER_YEARLY.amount_cents == 15900
    assert MEMBER_YEARLY.currency == "CNY"
    assert MEMBER_YEARLY.months == 12
    # 美元套餐：海外界面唯一可购目录（PayPal 不收 CNY），$4.9/$14.9 钉死
    assert MEMBER_MONTHLY_USD.code == "member_monthly_usd"
    assert MEMBER_MONTHLY_USD.amount_cents == 490
    assert MEMBER_MONTHLY_USD.currency == "USD"
    assert MEMBER_MONTHLY_USD.months == 1
    assert MEMBER_YEARLY_USD.code == "member_yearly_usd"
    assert MEMBER_YEARLY_USD.amount_cents == 1490
    assert MEMBER_YEARLY_USD.currency == "USD"
    assert MEMBER_YEARLY_USD.months == 12
    assert set(MEMBERSHIP_PLANS) == {
        "member_monthly",
        "member_yearly",
        "member_monthly_usd",
        "member_yearly_usd",
    }


def test_channel_currencies_are_pinned() -> None:
    # 渠道 × 币种兼容矩阵：CNY 只走国内渠道，USD 只走海外跳转槽
    assert CHANNEL_CURRENCIES == {
        "wechat_native": "CNY",
        "alipay_page": "CNY",
        "overseas_redirect": "USD",
    }


def test_extend_from_uses_calendar_months_not_fixed_days() -> None:
    # 日历年月：3/15 + 1 月 = 4/15（不是 +30 天）
    assert MEMBER_MONTHLY.extend_from(_dt(2026, 3, 15)) == _dt(2026, 4, 15)
    # 跨年：12/15 + 1 月 = 次年 1/15
    assert MEMBER_MONTHLY.extend_from(_dt(2026, 12, 15)) == _dt(2027, 1, 15)
    # 年付：8/19 + 12 月 = 次年 8/19
    assert MEMBER_YEARLY.extend_from(_dt(2026, 8, 19)) == _dt(2027, 8, 19)


def test_extend_from_clamps_month_end() -> None:
    # 1/31 + 1 月 → 2/28（平年钳制）
    assert MEMBER_MONTHLY.extend_from(_dt(2026, 1, 31)) == _dt(2026, 2, 28)
    # 闰年：2024/1/31 + 1 月 → 2024/2/29
    assert MEMBER_MONTHLY.extend_from(_dt(2024, 1, 31)) == _dt(2024, 2, 29)
    # 闰日续约年付：2024/2/29 + 12 月 → 2025/2/28
    assert MEMBER_YEARLY.extend_from(_dt(2024, 2, 29)) == _dt(2025, 2, 28)
    # 8/31 + 1 月 → 9/30
    assert MEMBER_MONTHLY.extend_from(_dt(2026, 8, 31)) == _dt(2026, 9, 30)
    # 时区保留
    extended = MEMBER_MONTHLY.extend_from(_dt(2026, 1, 31))
    assert extended.tzinfo is not None


def test_get_plan_is_fail_closed_on_unknown_codes() -> None:
    assert get_plan("member_monthly") is MEMBER_MONTHLY
    with pytest.raises(UnknownPlanError):
        get_plan("member_lifetime")
    with pytest.raises(UnknownPlanError):
        get_plan("")
    with pytest.raises(UnknownPlanError):
        get_plan(None)
    with pytest.raises(UnknownPlanError):
        get_plan(1900)


def test_effective_plans_merges_overrides() -> None:
    merged = effective_plans({"member_monthly": 2500, "member_yearly": 20000})
    assert merged["member_monthly"].amount_cents == 2500
    assert merged["member_yearly"].amount_cents == 20000
    # 覆盖只换金额：时长/币种/档位保持默认目录语义
    assert merged["member_monthly"].months == 1
    assert merged["member_yearly"].months == 12
    assert merged["member_yearly"].currency == "CNY"
    # 保序且默认常量不被污染
    assert list(merged) == list(MEMBERSHIP_PLANS)
    assert MEMBER_MONTHLY.amount_cents == 1900
    assert MEMBER_YEARLY.amount_cents == 15900


def test_effective_plans_empty_or_unknown_overrides_are_identity() -> None:
    assert effective_plans(None) == dict(MEMBERSHIP_PLANS)
    assert effective_plans({}) == dict(MEMBERSHIP_PLANS)
    merged = effective_plans({"member_lifetime": 99900})
    assert merged["member_monthly"].amount_cents == 1900
    assert merged["member_yearly"].amount_cents == 15900
    assert "member_lifetime" not in merged
