"""Ops 支付台账端点契约测试（骨架 PR-4）。

钉住：
- 全部端点 RequireAdmin（403 非管理员）且**不挂** payments_enabled 门控；
- 台账筛选/详情含 callback_payload + email（Ops 专属审计面）；
- mark-paid 与用户回调共用发放入口：幂等 200、closed 409、恰好一次；
- close 仅 pending → closed，终态 409；
- /ops/payments/plans 运行时调价：GET 默认投影、PUT 整体聚合
  （整数分 = upsert，null = 删覆盖恢复默认价），越界 400 中文 detail。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.dependencies import (
    get_payment_order_repository,
    get_payment_plan_overrides_repository,
    get_user_account_repository,
)
from backend.app.api.routes_ops_payments import router
from backend.app.core.auth import RequireAdmin
from backend.app.core.config import settings
from backend.app.repositories.payment_plan_overrides_repository import (
    PaymentPlanOverride,
)
from backend.tests.test_payments_api import FakeOrders, FakeUsers


class FakePlanOverrides:
    """payment_plan_overrides 内存替身：list/upsert/delete 最小语义。"""

    def __init__(self) -> None:
        self.rows: dict[str, int] = {}

    def list_plan_overrides(self) -> tuple[PaymentPlanOverride, ...]:
        return tuple(
            PaymentPlanOverride(plan_code=code, amount_cents=amount)
            for code, amount in sorted(self.rows.items())
        )

    def upsert_plan_override(
        self, *, plan_code: str, amount_cents: int
    ) -> PaymentPlanOverride:
        self.rows[plan_code] = amount_cents
        return PaymentPlanOverride(plan_code=plan_code, amount_cents=amount_cents)

    def delete_plan_override(self, plan_code: str) -> int:
        return 1 if self.rows.pop(plan_code, None) is not None else 0


@pytest.fixture()
def harness(monkeypatch: pytest.MonkeyPatch) -> Any:
    # 开关关闭也要可查可补（灰度期订单与历史台账）
    monkeypatch.setattr(settings, "payments_enabled", False)
    users = FakeUsers()
    users.add(7, email="buyer@example.com")
    orders = FakeOrders(users)
    plan_overrides = FakePlanOverrides()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[RequireAdmin] = lambda: {
        "user_id": 1,
        "role": "admin",
    }
    app.dependency_overrides[get_payment_order_repository] = lambda: orders
    app.dependency_overrides[get_user_account_repository] = lambda: users
    app.dependency_overrides[get_payment_plan_overrides_repository] = (
        lambda: plan_overrides
    )
    return SimpleNamespace(
        client=TestClient(app),
        app=app,
        users=users,
        orders=orders,
        plan_overrides=plan_overrides,
    )


def _create_order(
    harness: Any,
    *,
    user_id: int = 7,
    plan: str = "member_monthly",
    channel: str = "wechat_native",
    status: str = "pending",
) -> dict[str, Any]:
    from backend.tests.test_payments_api import NOW

    row = harness.orders.create_order(
        order_no=f"PTEST{harness.orders.next_id:04d}",
        user_id=user_id,
        plan_code=plan,
        channel=channel,
        amount_cents=1900 if plan == "member_monthly" else 15900,
        currency="CNY",
        idempotency_key="",
        expires_at=NOW,
    )
    assert row is not None
    if status != "pending":
        harness.orders.rows[row["order_no"]]["status"] = status
    return row


def test_require_admin(harness: Any) -> None:
    """非管理员 403：走真实 RequireAdmin + 替身 RequireUser 身份。"""
    from backend.app.core.auth import RequireUser

    harness.app.dependency_overrides.pop(RequireAdmin)
    harness.app.dependency_overrides[RequireUser] = lambda: {
        "user_id": 7,
        "role": "user",
    }
    assert harness.client.get("/api/ops/payments/orders").status_code == 403
    assert harness.client.post("/api/ops/payments/orders/P1/close").status_code == 403
    assert (
        harness.client.post("/api/ops/payments/orders/P1/mark-paid", json={})
        .status_code
        == 403
    )
    assert harness.client.get("/api/ops/payments/orders/P1").status_code == 403
    assert harness.client.get("/api/ops/payments/plans").status_code == 403
    assert (
        harness.client.put(
            "/api/ops/payments/plans", json={"monthly_amount_cents": 2500}
        ).status_code
        == 403
    )


def test_list_orders_admin_filters_and_includes_email(harness: Any) -> None:
    _create_order(harness, plan="member_monthly", channel="wechat_native")
    _create_order(harness, plan="member_yearly", channel="stripe")
    _create_order(harness, plan="member_monthly", channel="stripe", status="paid")

    all_resp = harness.client.get("/api/ops/payments/orders")
    assert all_resp.status_code == 200
    assert all_resp.json()["total"] == 3
    assert all_resp.json()["items"][0]["email"] == "buyer@example.com"

    by_status = harness.client.get("/api/ops/payments/orders?status=paid").json()
    assert by_status["total"] == 1
    assert by_status["items"][0]["status"] == "paid"

    by_channel = harness.client.get("/api/ops/payments/orders?channel=stripe").json()
    assert by_channel["total"] == 2

    by_email = harness.client.get("/api/ops/payments/orders?email=BUYER@").json()
    assert by_email["total"] == 3

    assert (
        harness.client.get("/api/ops/payments/orders?status=refunded").status_code
        == 400
    )


def test_get_order_admin_detail_includes_audit_columns(harness: Any) -> None:
    row = _create_order(harness)
    harness.orders.rows[row["order_no"]]["callback_payload"] = '{"raw":1}'
    response = harness.client.get(f"/api/ops/payments/orders/{row['order_no']}")
    assert response.status_code == 200
    body = response.json()
    assert body["callback_payload"] == '{"raw":1}'
    assert body["email"] == "buyer@example.com"
    assert harness.client.get("/api/ops/payments/orders/PNOPE").status_code == 404


def test_mark_paid_grants_and_is_idempotent(harness: Any) -> None:
    row = _create_order(harness)
    response = harness.client.post(
        f"/api/ops/payments/orders/{row['order_no']}/mark-paid", json={}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["granted"] is True
    assert body["order"]["status"] == "paid"
    assert body["order"]["channel_order_no"] == "ops-mark-paid:1"
    assert "ops_mark_paid" in body["order"]["callback_payload"]
    user = harness.users.get_user_by_id(7)
    assert user["membership_tier"] == "member"
    first_expiry = user["membership_expires_at"]

    # 重复补单：幂等 200，不再顺延
    again = harness.client.post(
        f"/api/ops/payments/orders/{row['order_no']}/mark-paid", json={}
    )
    assert again.status_code == 200
    assert again.json()["granted"] is False
    assert again.json()["note"] == "already_paid"
    assert harness.users.get_user_by_id(7)["membership_expires_at"] == first_expiry


def test_mark_paid_closed_order_409(harness: Any) -> None:
    row = _create_order(harness, status="closed")
    response = harness.client.post(
        f"/api/ops/payments/orders/{row['order_no']}/mark-paid", json={}
    )
    assert response.status_code == 409
    assert harness.users.get_user_by_id(7)["membership_tier"] == "free"


def test_mark_paid_expired_order_grants(harness: Any) -> None:
    # 迟到支付的人工补单：expired 特许边与回调路径同一语义
    row = _create_order(harness, status="expired")
    response = harness.client.post(
        f"/api/ops/payments/orders/{row['order_no']}/mark-paid", json={}
    )
    assert response.status_code == 200
    assert response.json()["granted"] is True
    assert harness.users.get_user_by_id(7)["membership_tier"] == "member"


def test_close_order_only_from_pending(harness: Any) -> None:
    row = _create_order(harness)
    response = harness.client.post(f"/api/ops/payments/orders/{row['order_no']}/close")
    assert response.status_code == 200
    assert response.json()["order"]["status"] == "closed"
    # 终态 409（closed 幂等也是 409：人工动作应显式而非静默成功）
    assert (
        harness.client.post(f"/api/ops/payments/orders/{row['order_no']}/close")
        .status_code
        == 409
    )

    paid = _create_order(harness, status="paid")
    assert (
        harness.client.post(f"/api/ops/payments/orders/{paid['order_no']}/close")
        .status_code
        == 409
    )
    expired = _create_order(harness, status="expired")
    assert (
        harness.client.post(f"/api/ops/payments/orders/{expired['order_no']}/close")
        .status_code
        == 409
    )


def test_get_plan_pricing_default_projection(harness: Any) -> None:
    """缺行 = plans.py 默认价；payments_enabled=False（fixture 已置）也可达。"""
    response = harness.client.get("/api/ops/payments/plans")
    assert response.status_code == 200
    plans = response.json()["plans"]
    assert [plan["code"] for plan in plans] == ["member_monthly", "member_yearly"]
    monthly, yearly = plans
    assert monthly["default_amount_cents"] == 1900
    assert monthly["override_amount_cents"] is None
    assert monthly["amount_cents"] == 1900
    assert monthly["months"] == 1
    assert yearly["default_amount_cents"] == 15900
    assert yearly["override_amount_cents"] is None
    assert yearly["amount_cents"] == 15900
    assert yearly["months"] == 12
    assert yearly["currency"] == "CNY"
    assert monthly["updated_at"] is None


def test_put_plan_pricing_upsert_overrides(harness: Any) -> None:
    response = harness.client.put(
        "/api/ops/payments/plans",
        json={"monthly_amount_cents": 2500, "yearly_amount_cents": 20000},
    )
    assert response.status_code == 200
    plans = {plan["code"]: plan for plan in response.json()["plans"]}
    assert plans["member_monthly"]["override_amount_cents"] == 2500
    assert plans["member_monthly"]["amount_cents"] == 2500
    assert plans["member_yearly"]["override_amount_cents"] == 20000
    assert plans["member_yearly"]["amount_cents"] == 20000
    # 默认价列不被覆盖污染
    assert plans["member_monthly"]["default_amount_cents"] == 1900
    assert plans["member_yearly"]["default_amount_cents"] == 15900
    assert harness.plan_overrides.rows == {
        "member_monthly": 2500,
        "member_yearly": 20000,
    }


def test_put_plan_pricing_null_restores_default(harness: Any) -> None:
    harness.plan_overrides.rows["member_monthly"] = 2500
    response = harness.client.put(
        "/api/ops/payments/plans",
        json={"monthly_amount_cents": None, "yearly_amount_cents": 20000},
    )
    assert response.status_code == 200
    plans = {plan["code"]: plan for plan in response.json()["plans"]}
    assert plans["member_monthly"]["override_amount_cents"] is None
    assert plans["member_monthly"]["amount_cents"] == 1900
    assert plans["member_yearly"]["amount_cents"] == 20000
    assert harness.plan_overrides.rows == {"member_yearly": 20000}


def test_put_plan_pricing_out_of_bounds_400(harness: Any) -> None:
    for bad in (0, 99, 1000001):
        response = harness.client.put(
            "/api/ops/payments/plans", json={"monthly_amount_cents": bad}
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "套餐价格必须是 100-1000000 之间的整数分"
    # 越界请求不落库
    assert harness.plan_overrides.rows == {}
