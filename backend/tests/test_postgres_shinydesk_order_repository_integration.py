"""shinydesk_orders 的 PostgreSQL 仓储集成测试（迁移 0100；无 TEST_POSTGRES_DSN 时跳过）。

与 InMemoryShinyDeskOrderRepository 同语义：条件更新的状态前提、PayPal 单号/
capture id 唯一冲突收口为 None、邮件认领次数上限、找回失败计数。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend.app.repositories.postgres_shinydesk_order_repository import PostgresShinyDeskOrderRepository
from backend.tests.postgres_test_safety import postgres_test_sandbox

NOW = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def repository():
    with postgres_test_sandbox() as sandbox:
        yield PostgresShinyDeskOrderRepository(sandbox.database)


def _create(repository, order_no="SD20261030100000ABCDEF01"):
    return repository.create_order(
        order_no=order_no,
        product_code="shinydesk_standard_usd",
        amount_cents=999,
        currency="USD",
        access_token_hash="a" * 64,
        client_ip="203.0.113.9",
        expires_at=NOW + timedelta(hours=3),
    )


def _pay(repository, row, paypal_order_id="PAYPALORDER000001", capture_id="CAPTURE0000000001"):
    return repository.mark_paid(
        order_id=row["id"],
        paypal_order_id=paypal_order_id,
        capture_id=capture_id,
        payer_email="buyer@example.com",
        paid_at=NOW,
        callback_payload="{}",
    )


def test_create_is_unique_by_order_no(repository) -> None:
    row = _create(repository)
    assert row["status"] == "pending" and row["paypal_order_id"] is None
    assert _create(repository) is None


def test_paypal_order_binding_is_exclusive(repository) -> None:
    first = _create(repository)
    second = _create(repository, "SD20261030100000ABCDEF02")
    assert repository.bind_paypal_order(order_id=first["id"], paypal_order_id="PAYPALORDER000001")["paypal_order_id"] == "PAYPALORDER000001"
    assert repository.bind_paypal_order(order_id=first["id"], paypal_order_id="PAYPALORDER000001") is not None
    assert repository.bind_paypal_order(order_id=first["id"], paypal_order_id="PAYPALORDER000009") is None
    assert repository.bind_paypal_order(order_id=second["id"], paypal_order_id="PAYPALORDER000001") is None


def test_paid_fulfilled_revoked_transitions_are_conditional(repository) -> None:
    row = _create(repository)
    paid = _pay(repository, row)
    assert paid["status"] == "paid" and paid["paypal_capture_id"] == "CAPTURE0000000001"
    assert _pay(repository, row) is None  # 重放
    other = _create(repository, "SD20261030100000ABCDEF02")
    assert _pay(repository, other, paypal_order_id="PAYPALORDER000002") is None  # capture id 被占
    fulfilled = repository.mark_fulfilled(order_id=row["id"], license_code="PB-" + "A" * 40, license_id="lic")
    assert fulfilled["status"] == "fulfilled" and fulfilled["fulfilled_at"] is not None
    assert repository.mark_fulfilled(order_id=row["id"], license_code="PB-" + "B" * 40, license_id="x") is None
    assert repository.get_by_capture_id("CAPTURE0000000001")["license_code"] == "PB-" + "A" * 40
    revoked = repository.mark_revoked(order_id=row["id"], reason="refund")
    assert revoked["status"] == "revoked" and revoked["revoke_reason"] == "refund"
    assert repository.mark_revoked(order_id=row["id"], reason="manual") is None
    assert repository.mark_revoked(order_id=other["id"], reason="manual") is None  # pending 不能作废


def test_email_claim_is_single_flight_and_capped(repository) -> None:
    row = _create(repository)
    _pay(repository, row)
    assert repository.claim_email(order_id=row["id"]) is None  # 未发码前不发信
    repository.mark_fulfilled(order_id=row["id"], license_code="PB-" + "A" * 40, license_id="lic")
    for attempt in range(1, 4):
        claimed = repository.claim_email(order_id=row["id"])
        assert claimed["email_attempts"] == attempt and claimed["email_status"] == "sending"
        assert repository.claim_email(order_id=row["id"]) is None  # 发送中不可重复认领
        repository.finish_email(order_id=row["id"], status="failed")
    assert repository.claim_email(order_id=row["id"]) is None  # 3 次封顶
    repository.reset_email(order_id=row["id"])
    assert repository.claim_email(order_id=row["id"])["email_attempts"] == 1


def test_lookup_failures_dispute_and_listing(repository) -> None:
    row = _create(repository)
    _pay(repository, row)
    repository.record_lookup_failure(order_id=row["id"])
    repository.record_lookup_failure(order_id=row["id"])
    repository.set_dispute_status(order_id=row["id"], dispute_status="OPEN")
    repository.record_error(order_id=row["id"], error="license service unreachable")
    current = repository.get_by_order_no(row["order_no"])
    assert (current["lookup_failures"], current["dispute_status"], current["last_error"]) == (2, "OPEN", "license service unreachable")
    rows, total = repository.list_orders(query="BUYER@example.com", page=1, page_size=10)
    assert total == 1 and rows[0]["order_no"] == row["order_no"]
    assert repository.list_orders(query="", page=1, page_size=10)[1] == 1
