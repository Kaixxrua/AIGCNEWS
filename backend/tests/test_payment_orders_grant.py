"""订单状态机与会员发放服务单测（支付骨架 PR-2）。

恰好一次的财产在仓储层条件 UPDATE（PG 集成测覆盖）；这里用替身仓储
钉服务层的编排语义：续费叠加三态、重放幂等、长期有效会员不顺延。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from backend.app.services.payments.grant import (
    compute_grant_expiry,
    mark_paid_and_grant,
)
from backend.app.services.payments.orders import (
    ALLOWED_TRANSITIONS,
    ORDER_STATUS_CLOSED,
    ORDER_STATUS_EXPIRED,
    ORDER_STATUS_PAID,
    ORDER_STATUS_PENDING,
    PAYABLE_STATUSES,
    InvalidOrderTransition,
    assert_transition,
    normalize_order_status,
)
from backend.app.services.payments.plans import MEMBER_MONTHLY, MEMBER_YEARLY
from backend.app.services.payments.providers.base import VerifiedCallback

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


# ── 状态机 ─────────────────────────────────────────────────────────────


def test_pending_can_reach_paid_expired_closed() -> None:
    for new in (ORDER_STATUS_PAID, ORDER_STATUS_EXPIRED, ORDER_STATUS_CLOSED):
        assert_transition(ORDER_STATUS_PENDING, new)


def test_late_payment_expired_to_paid_is_the_only_escape() -> None:
    assert ALLOWED_TRANSITIONS[ORDER_STATUS_EXPIRED] == frozenset({ORDER_STATUS_PAID})
    assert PAYABLE_STATUSES == frozenset({ORDER_STATUS_PENDING, ORDER_STATUS_EXPIRED})
    assert_transition(ORDER_STATUS_EXPIRED, ORDER_STATUS_PAID)
    with pytest.raises(InvalidOrderTransition):
        assert_transition(ORDER_STATUS_EXPIRED, ORDER_STATUS_CLOSED)


def test_paid_and_closed_are_absorbing() -> None:
    for terminal in (ORDER_STATUS_PAID, ORDER_STATUS_CLOSED):
        assert ALLOWED_TRANSITIONS[terminal] == frozenset()
        for new in (ORDER_STATUS_PENDING, ORDER_STATUS_PAID, ORDER_STATUS_EXPIRED):
            with pytest.raises(InvalidOrderTransition):
                assert_transition(terminal, new)


def test_unknown_status_normalizes_fail_closed_to_closed() -> None:
    assert normalize_order_status("paid") == ORDER_STATUS_PAID
    assert normalize_order_status("refunded") == ORDER_STATUS_CLOSED
    assert normalize_order_status("") == ORDER_STATUS_CLOSED
    assert normalize_order_status(None) == ORDER_STATUS_CLOSED


# ── 发放：续费叠加三态 ────────────────────────────────────────────────


def test_free_user_extends_from_now() -> None:
    new_expires_at, note = compute_grant_expiry(
        user={"membership_tier": "free", "membership_expires_at": None},
        plan=MEMBER_MONTHLY,
        now=NOW,
    )
    assert new_expires_at == datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    assert note == ""


def test_active_member_stacks_on_existing_expiry() -> None:
    existing = NOW + timedelta(days=10)  # 会员还剩 10 天
    new_expires_at, note = compute_grant_expiry(
        user={"membership_tier": "member", "membership_expires_at": existing},
        plan=MEMBER_MONTHLY,
        now=NOW,
    )
    # 从现有到期日顺延一个月，而非从现在开始
    assert new_expires_at == datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    assert note == ""


def test_expired_member_restarts_from_now() -> None:
    expired = NOW - timedelta(days=3)
    new_expires_at, _ = compute_grant_expiry(
        user={"membership_tier": "member", "membership_expires_at": expired},
        plan=MEMBER_YEARLY,
        now=NOW,
    )
    assert new_expires_at == datetime(2027, 8, 19, 12, 0, tzinfo=timezone.utc)


def test_permanent_member_is_paid_but_not_extended() -> None:
    new_expires_at, note = compute_grant_expiry(
        user={"membership_tier": "member", "membership_expires_at": None},
        plan=MEMBER_MONTHLY,
        now=NOW,
    )
    assert new_expires_at is None
    assert note == "permanent_member_noop"


# ── 发放：编排（替身仓储） ────────────────────────────────────────────


class _FakeUsers:
    def __init__(self, user: dict[str, Any] | None) -> None:
        self._user = user

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        return self._user


class _FakeOrders:
    """替身仓储：模拟条件 UPDATE 的恰好一次语义。"""

    def __init__(self, *, win_once: bool = True) -> None:
        self._remaining_wins = 1 if win_once else 0
        self.calls: list[dict[str, Any]] = []

    def mark_paid_and_grant(self, **kwargs: Any) -> dict[str, Any] | None:
        self.calls.append(kwargs)
        if self._remaining_wins <= 0:
            return None
        self._remaining_wins -= 1
        return {"id": kwargs["order_id"], "status": "paid"}


def _verified() -> VerifiedCallback:
    return VerifiedCallback(
        order_no="P20260819001",
        channel_order_no="ch-txn-1",
        amount_cents=1900,
        currency="CNY",
        paid_at=NOW,
    )


def _order() -> dict[str, Any]:
    return {"id": 42, "user_id": 7, "order_no": "P20260819001", "status": "pending"}


def test_mark_paid_and_grant_happy_path_writes_membership() -> None:
    orders = _FakeOrders()
    users = _FakeUsers({"id": 7, "membership_tier": "free", "membership_expires_at": None})
    result = mark_paid_and_grant(
        orders=orders,  # type: ignore[arg-type]
        users=users,  # type: ignore[arg-type]
        order=_order(),
        verified=_verified(),
        plan=MEMBER_MONTHLY,
        now=NOW,
        callback_payload='{"raw":"body"}',
    )
    assert result.granted is True
    assert result.new_expires_at == datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    call = orders.calls[0]
    assert call["order_id"] == 42
    assert call["channel_order_no"] == "ch-txn-1"
    assert call["callback_payload"] == '{"raw":"body"}'
    assert call["grant_expires_at"] == result.new_expires_at
    assert call["user_id"] == 7
    assert call["new_membership_tier"] == "member"
    assert call["new_membership_expires_at"] == result.new_expires_at


def test_mark_paid_and_grant_replay_is_idempotent_noop() -> None:
    orders = _FakeOrders(win_once=False)  # 条件更新 rowcount=0
    users = _FakeUsers({"id": 7, "membership_tier": "free", "membership_expires_at": None})
    result = mark_paid_and_grant(
        orders=orders,  # type: ignore[arg-type]
        users=users,  # type: ignore[arg-type]
        order=_order(),
        verified=_verified(),
        plan=MEMBER_MONTHLY,
        now=NOW,
    )
    assert result.granted is False
    assert result.note == "already_processed"
    assert result.order is None


def test_mark_paid_and_grant_missing_user_changes_nothing() -> None:
    orders = _FakeOrders()
    result = mark_paid_and_grant(
        orders=orders,  # type: ignore[arg-type]
        users=_FakeUsers(None),  # type: ignore[arg-type]
        order=_order(),
        verified=_verified(),
        plan=MEMBER_MONTHLY,
        now=NOW,
    )
    assert result.granted is False
    assert result.note == "user_missing"
    assert orders.calls == []  # 零写入
