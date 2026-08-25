from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    create_postgres_pool,
)
from backend.app.core.postgres_migrations import PostgresMigrationRunner
from backend.app.repositories.postgres_payment_order_repository import (
    PostgresPaymentOrderRepository,
)
from backend.app.repositories.postgres_user_account_repository import (
    PostgresUserAccountRepository,
)

pytestmark = pytest.mark.skipif(
    os.getenv("POSTGRES_INTEGRATION") != "1",
    reason="set POSTGRES_INTEGRATION=1 to run PostgreSQL integration tests",
)

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def database():
    lifecycle = PostgresDatabaseLifecycle(create_postgres_pool)
    lifecycle.open()
    PostgresMigrationRunner(lifecycle).apply()
    with lifecycle.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE users RESTART IDENTITY CASCADE")
    try:
        yield lifecycle
    finally:
        lifecycle.close()


@pytest.fixture
def user_id(database):
    return PostgresUserAccountRepository(database).create_user_with_email(
        "buyer@example.com",
        "hash",
    )


def _create(repository, user_id, **overrides):
    params = {
        "order_no": "M20260819120000000001ab12",
        "user_id": user_id,
        "plan_code": "member_monthly",
        "channel": "wechat_native",
        "amount_cents": 1900,
        "currency": "CNY",
        "idempotency_key": "",
        "expires_at": NOW + timedelta(minutes=30),
    }
    params.update(overrides)
    row = repository.create_order(**params)
    assert row is not None
    return row


def test_payment_order_create_and_read_round_trip(database, user_id) -> None:
    repository = PostgresPaymentOrderRepository(database)

    order = _create(repository, user_id)
    assert order["order_no"] == "M20260819120000000001ab12"
    assert order["status"] == "pending"
    assert order["amount_cents"] == 1900
    assert order["currency"] == "CNY"

    fetched = repository.get_order_by_order_no(order["order_no"])
    assert fetched is not None and fetched["id"] == order["id"]

    items, total = repository.list_user_orders(user_id=user_id, page=1, page_size=10)
    assert total == 1 and [item["id"] for item in items] == [order["id"]]
    other_items, other_total = repository.list_user_orders(
        user_id=user_id + 999, page=1, page_size=10
    )
    assert other_total == 0 and other_items == []


def test_payment_order_idempotency_key_conflict_returns_none(database, user_id) -> None:
    repository = PostgresPaymentOrderRepository(database)

    first = _create(repository, user_id, idempotency_key="checkout-attempt-1")
    conflict = repository.create_order(
        order_no="M20260819120100000001cd34",
        user_id=user_id,
        plan_code="member_monthly",
        channel="wechat_native",
        amount_cents=1900,
        currency="CNY",
        idempotency_key="checkout-attempt-1",
        expires_at=NOW + timedelta(minutes=30),
    )
    assert conflict is None

    existing = repository.get_order_by_user_and_idempotency_key(
        user_id=user_id, idempotency_key="checkout-attempt-1"
    )
    assert existing is not None and existing["id"] == first["id"]
    _, total = repository.list_user_orders(user_id=user_id, page=1, page_size=10)
    assert total == 1


def test_payment_order_mark_paid_and_grant_is_exactly_once(database, user_id) -> None:
    repository = PostgresPaymentOrderRepository(database)
    users = PostgresUserAccountRepository(database)
    order = _create(repository, user_id)

    grant_expiry = NOW + timedelta(days=31)
    paid = repository.mark_paid_and_grant(
        order_id=order["id"],
        channel_order_no="wx-txn-1",
        paid_at=NOW,
        callback_payload='{"transaction_id":"wx-txn-1"}',
        grant_expires_at=grant_expiry,
        user_id=user_id,
        new_membership_tier="member",
        new_membership_expires_at=grant_expiry,
    )
    assert paid is not None
    assert paid["status"] == "paid"
    assert paid["channel_order_no"] == "wx-txn-1"
    assert paid["grant_expires_at"] == grant_expiry

    user = users.get_user_by_id(user_id)
    assert user["membership_tier"] == "member"
    assert user["membership_expires_at"] == grant_expiry

    # 渠道重发/并发重放：条件更新 rowcount=0 → None，用户到期时间不再叠加
    later_grant = grant_expiry + timedelta(days=31)
    replay = repository.mark_paid_and_grant(
        order_id=order["id"],
        channel_order_no="wx-txn-1",
        paid_at=NOW,
        callback_payload="{}",
        grant_expires_at=later_grant,
        user_id=user_id,
        new_membership_tier="member",
        new_membership_expires_at=later_grant,
    )
    assert replay is None
    assert users.get_user_by_id(user_id)["membership_expires_at"] == grant_expiry


def test_payment_order_late_payment_expired_to_paid(database, user_id) -> None:
    repository = PostgresPaymentOrderRepository(database)
    order = _create(repository, user_id, expires_at=NOW - timedelta(minutes=1))

    closed_count = repository.mark_expired_overdue(now=NOW, limit=100)
    assert closed_count == 1
    assert repository.get_order_by_order_no(order["order_no"])["status"] == "expired"

    # 迟到支付（expired → paid 特许边）仍可发放
    paid = repository.mark_paid_and_grant(
        order_id=order["id"],
        channel_order_no="wx-txn-late",
        paid_at=NOW,
        callback_payload="{}",
        grant_expires_at=NOW + timedelta(days=31),
        user_id=user_id,
        new_membership_tier="member",
        new_membership_expires_at=NOW + timedelta(days=31),
    )
    assert paid is not None and paid["status"] == "paid"


def test_payment_order_close_only_from_pending(database, user_id) -> None:
    repository = PostgresPaymentOrderRepository(database)
    order = _create(repository, user_id)

    closed = repository.close_order(order_id=order["id"])
    assert closed is not None and closed["status"] == "closed"
    # 终态重复关单 → None（路由层映射 409）
    assert repository.close_order(order_id=order["id"]) is None

    paid_order = _create(
        repository, user_id, order_no="M20260819120200000001ef56"
    )
    repository.mark_paid_and_grant(
        order_id=paid_order["id"],
        channel_order_no="txn",
        paid_at=NOW,
        callback_payload="{}",
        grant_expires_at=None,
        user_id=user_id,
        new_membership_tier="member",
        new_membership_expires_at=None,
    )
    assert repository.close_order(order_id=paid_order["id"]) is None


def test_payment_order_mark_expired_overdue_respects_limit(database, user_id) -> None:
    repository = PostgresPaymentOrderRepository(database)
    overdue = NOW - timedelta(minutes=1)
    for index in range(3):
        _create(
            repository,
            user_id,
            order_no=f"M2026081912{index:02d}00000001zz{index:02d}",
            expires_at=overdue,
        )
    _create(
        repository,
        user_id,
        order_no="M20260819129900000001zz99",
        expires_at=NOW + timedelta(minutes=30),
    )

    assert repository.mark_expired_overdue(now=NOW, limit=2) == 2
    assert repository.mark_expired_overdue(now=NOW, limit=2) == 1
    assert repository.mark_expired_overdue(now=NOW, limit=2) == 0

    items, total = repository.list_user_orders(user_id=user_id, page=1, page_size=10)
    assert total == 4
    statuses = {item["order_no"]: item["status"] for item in items}
    assert statuses["M20260819129900000001zz99"] == "pending"
    assert (
        sum(1 for status in statuses.values() if status == "expired") == 3
    )


def test_payment_order_admin_list_filters_and_joins_email(database, user_id) -> None:
    repository = PostgresPaymentOrderRepository(database)
    _create(repository, user_id, plan_code="member_monthly", channel="wechat_native")
    # channel="stripe" 行模拟历史订单：渠道已下线但台账筛选须容忍存量值
    _create(
        repository,
        user_id,
        order_no="M20260819120300000001gh78",
        plan_code="member_yearly",
        channel="stripe",
    )

    items, total = repository.list_orders_admin(
        status=None, channel=None, plan_code=None, email=None,
        created_from=None, created_to=None, page=1, page_size=10,
    )
    assert total == 2
    assert all(item["user_email"] == "buyer@example.com" for item in items)

    items, total = repository.list_orders_admin(
        status=None, channel="stripe", plan_code=None, email=None,
        created_from=None, created_to=None, page=1, page_size=10,
    )
    assert total == 1 and items[0]["channel"] == "stripe"

    items, total = repository.list_orders_admin(
        status=None, channel=None, plan_code="member_yearly", email="BUYER@example.com",
        created_from=None, created_to=None, page=1, page_size=10,
    )
    assert total == 1 and items[0]["plan_code"] == "member_yearly"
