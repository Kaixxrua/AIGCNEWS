"""渠道回调管线契约测试（骨架 PR-3，FakeProvider 驱动）。

回调是收费系统唯一的钱→权益闸门，钉住：
- 验签失败 → 渠道失败 ACK（400），零状态变更；
- 单号不存在 404；渠道归属/渠道单号漂移 422；
- 金额/币种不符 → 422 + error_events，零状态变更（fail-closed）；
- 已 paid 快速 ok ACK；pending/expired → 恰好一次发放；closed 吸态 422；
- 重放不再顺延会员到期日（幂等）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app.api.feature_gates import require_membership_purchase_enabled
from backend.app.services.payments.plans import MEMBER_MONTHLY
from backend.app.services.payments.providers.base import (
    CallbackVerificationError,
    VerifiedCallback,
)
from backend.tests.test_payments_api import (
    _create,
    harness,  # noqa: F401  (fixture re-export)
)

PAID_AT = datetime(2026, 8, 19, 12, 30, tzinfo=timezone.utc)


def _verified(order: dict, *, amount: int | None = None) -> VerifiedCallback:
    return VerifiedCallback(
        order_no=order["order_no"],
        channel_order_no="ch-txn-1",
        amount_cents=amount if amount is not None else order["amount_cents"],
        currency=order["currency"],
        paid_at=PAID_AT,
    )


def _callback(client: TestClient, channel: str = "wechat_native"):
    return client.post(
        f"/api/payments/callback/{channel}",
        content=b'{"channel":"raw"}',
        headers={"Content-Type": "application/json"},
    )


def test_purchase_retirement_preserves_existing_orders_and_verified_callbacks(harness) -> None:  # noqa: F811
    # Seed an order created before retirement, then restore the production gate.
    order = _create(harness)
    harness.app.dependency_overrides.pop(require_membership_purchase_enabled)
    assert harness.client.get("/api/payments/orders").status_code == 200
    assert harness.client.get(f"/api/payments/orders/{order['order_no']}").status_code == 200
    harness.provider._verified = _verified(order)
    assert _callback(harness.client).status_code == 200
    expiry = harness.users.get_user_by_id(7)["membership_expires_at"]
    assert harness.orders.rows[order["order_no"]]["status"] == "paid"
    assert _callback(harness.client).status_code == 200
    assert harness.users.get_user_by_id(7)["membership_expires_at"] == expiry
    assert harness.client.post("/api/payments/orders", json={}).status_code == 410


# ── 验签与查单 ───────────────────────────────────────────────────────────


def test_unknown_channel_404(harness) -> None:  # noqa: F811
    assert _callback(harness.client, "paypal").status_code == 404


def test_verification_failure_returns_fail_ack_and_changes_nothing(harness) -> None:  # noqa: F811
    harness.provider._verify_error = CallbackVerificationError("bad signature")
    response = _callback(harness.client)
    assert response.status_code == 400
    assert response.json() == {"ok": False}
    assert harness.orders.rows == {}


def test_verified_non_final_event_gets_ok_ack_and_changes_nothing(harness) -> None:  # noqa: F811
    """验签通过但非终态事件（如 PayPal APPROVED 已自动 capture）→ 200 ACK、零状态变更。"""
    order = _create(harness)
    harness.provider._verified_none = True

    response = _callback(harness.client)
    assert response.status_code == 200
    assert response.json() == {"ok": True}

    row = harness.orders.rows[order["order_no"]]
    assert row["status"] == "pending"
    assert row["channel_order_no"] == ""
    assert row["callback_payload"] == ""
    assert harness.users.get_user_by_id(7)["membership_tier"] == "free"
    assert harness.error_events.events == []


def test_unknown_order_no_404(harness) -> None:  # noqa: F811
    harness.provider._verified = _verified(
        {"order_no": "PGHOST", "amount_cents": 1, "currency": "CNY"}
    )
    assert _callback(harness.client).status_code == 404


# ── 一致性校验 ───────────────────────────────────────────────────────────


def test_channel_attribution_mismatch_422(harness) -> None:  # noqa: F811
    order = _create(harness)  # wechat_native 下单
    harness.providers["alipay_page"]._verified = _verified(order)
    # 同一单号从 alipay_page 入口回调 → 渠道归属不符
    assert _callback(harness.client, "alipay_page").status_code == 422
    assert harness.orders.rows[order["order_no"]]["status"] == "pending"


def test_channel_order_no_drift_422(harness) -> None:  # noqa: F811
    order = _create(harness)
    harness.provider._verified = _verified(order)
    assert _callback(harness.client).status_code == 200
    # 已绑定 ch-txn-1，重放报文换成别的渠道单号 → 漂移拒绝
    harness.provider._verified = VerifiedCallback(
        order_no=order["order_no"],
        channel_order_no="ch-txn-OTHER",
        amount_cents=order["amount_cents"],
        currency="CNY",
        paid_at=PAID_AT,
    )
    assert _callback(harness.client).status_code == 422


# ── 金额 fail-closed ─────────────────────────────────────────────────────


def test_amount_mismatch_422_records_error_and_changes_nothing(harness) -> None:  # noqa: F811
    order = _create(harness)
    harness.provider._verified = _verified(order, amount=1)
    response = _callback(harness.client)
    assert response.status_code == 422
    assert response.json()["detail"] == "amount_mismatch"
    row = harness.orders.rows[order["order_no"]]
    assert row["status"] == "pending"
    assert row["paid_at"] is None
    assert harness.users.get_user_by_id(7)["membership_tier"] == "free"
    assert len(harness.error_events.events) == 1
    assert "amount mismatch" in harness.error_events.events[0].message


# ── 发放路径 ─────────────────────────────────────────────────────────────


def test_pending_order_grants_membership_exactly_once(harness) -> None:  # noqa: F811
    order = _create(harness)  # member_monthly
    harness.provider._verified = _verified(order)

    response = _callback(harness.client)
    assert response.status_code == 200
    assert response.json() == {"ok": True}

    row = harness.orders.rows[order["order_no"]]
    assert row["status"] == "paid"
    assert row["channel_order_no"] == "ch-txn-1"
    assert row["callback_payload"] == '{"channel":"raw"}'
    user = harness.users.get_user_by_id(7)
    assert user["membership_tier"] == "member"
    first_expiry = user["membership_expires_at"]
    assert first_expiry is not None

    # 渠道重发：快速 ACK，到期日不再顺延
    assert _callback(harness.client).status_code == 200
    assert harness.users.get_user_by_id(7)["membership_expires_at"] == first_expiry


def test_expired_order_late_payment_still_grants(harness) -> None:  # noqa: F811
    order = _create(harness)
    harness.orders.rows[order["order_no"]]["status"] = "expired"
    harness.provider._verified = _verified(order)
    assert _callback(harness.client).status_code == 200
    assert harness.users.get_user_by_id(7)["membership_tier"] == "member"
    assert harness.orders.rows[order["order_no"]]["status"] == "paid"


def test_closed_order_is_absorbing_422(harness) -> None:  # noqa: F811
    order = _create(harness)
    harness.orders.rows[order["order_no"]]["status"] = "closed"
    harness.provider._verified = _verified(order)
    assert _callback(harness.client).status_code == 422
    assert harness.users.get_user_by_id(7)["membership_tier"] == "free"
    assert len(harness.error_events.events) == 1


def test_active_member_renews_from_existing_expiry(harness) -> None:  # noqa: F811
    existing_expiry = datetime.now(timezone.utc) + timedelta(days=10)
    harness.users.add(7, tier="member", expires_at=existing_expiry)
    order = _create(harness)  # member_monthly
    harness.provider._verified = _verified(order)
    assert _callback(harness.client).status_code == 200
    user = harness.users.get_user_by_id(7)
    # 在现有到期日上顺延一个月，非从回调时刻起算；fixture 须锚定真实时钟，
    # 否则时间走过 fixture 到期日后该会员实际已过期，用例退化为过期续费语义
    assert user["membership_expires_at"] == MEMBER_MONTHLY.extend_from(existing_expiry)
