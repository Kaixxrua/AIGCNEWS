"""支付用户侧 API 契约测试（骨架 PR-3，FakeProvider 驱动）。

钉住的对外语义：
- payments_enabled=False → 整组 404（与未部署收费能力一致）；
- 下单校验链：401 → unknown_plan 400 → unknown_channel 400 → 渠道未配置 503；
- 幂等键重复提交返回既有单号；订单详情非属主与不存在同形 404；
- 用户侧任何响应都不得泄露 callback_payload / idempotency_key。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from backend.app.api.dependencies import (
    get_error_event_repository,
    get_payment_order_repository,
    get_payment_providers,
    get_user_account_repository,
)
from backend.app.api.feature_gates import require_membership_purchase_enabled
from backend.app.api.routes_payments import router
from backend.app.core.auth import RequireUser
from backend.app.core.config import settings
from backend.app.services.payments.providers.base import (
    PaymentInstruction,
    ProviderNotConfiguredError,
    VerifiedCallback,
)

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


class FakeOrders:
    """内存订单仓储：模拟唯一约束与条件更新的恰好一次语义。"""

    def __init__(self, users: "FakeUsers | None" = None) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.next_id = 1
        self.users = users

    def create_order(self, **kwargs: Any) -> dict[str, Any] | None:
        idempotency_key = kwargs["idempotency_key"]
        if idempotency_key and any(
            row["user_id"] == kwargs["user_id"]
            and row["idempotency_key"] == idempotency_key
            for row in self.rows.values()
        ):
            return None
        row = {
            "id": self.next_id,
            **kwargs,
            "status": "pending",
            "channel_order_no": "",
            "callback_payload": "",
            "paid_at": None,
            "grant_expires_at": None,
            "created_at": NOW,
            "updated_at": NOW,
        }
        self.next_id += 1
        self.rows[row["order_no"]] = row
        return dict(row)

    def get_order_by_order_no(self, order_no: str) -> dict[str, Any] | None:
        row = self.rows.get(order_no)
        return dict(row) if row is not None else None

    def get_order_by_user_and_idempotency_key(
        self, *, user_id: int, idempotency_key: str
    ) -> dict[str, Any] | None:
        for row in self.rows.values():
            if row["user_id"] == user_id and row["idempotency_key"] == idempotency_key:
                return dict(row)
        return None

    def list_user_orders(
        self, *, user_id: int, page: int, page_size: int
    ) -> tuple[list[dict[str, Any]], int]:
        mine = sorted(
            (row for row in self.rows.values() if row["user_id"] == user_id),
            key=lambda row: row["id"],
            reverse=True,
        )
        start = (page - 1) * page_size
        return [dict(row) for row in mine[start : start + page_size]], len(mine)

    def list_orders_admin(self, **filters: Any) -> tuple[list[dict[str, Any]], int]:
        """台账筛选（email 模糊匹配经 users join 模拟）+ id DESC 分页。"""
        rows = list(self.rows.values())
        if filters.get("status"):
            rows = [r for r in rows if r["status"] == filters["status"]]
        if filters.get("channel"):
            rows = [r for r in rows if r["channel"] == filters["channel"]]
        if filters.get("plan_code"):
            rows = [r for r in rows if r["plan_code"] == filters["plan_code"]]
        email = filters.get("email")
        if email and self.users is not None:
            rows = [
                r
                for r in rows
                if email.lower()
                in str(self.users.users.get(r["user_id"], {}).get("email", "")).lower()
            ]
        rows.sort(key=lambda row: row["id"], reverse=True)
        page = filters["page"]
        page_size = filters["page_size"]
        start = (page - 1) * page_size
        page_rows = []
        for row in rows[start : start + page_size]:
            enriched = dict(row)
            if self.users is not None:
                enriched["email"] = self.users.users.get(row["user_id"], {}).get("email")
            page_rows.append(enriched)
        return page_rows, len(rows)

    def mark_paid_and_grant(self, **kwargs: Any) -> dict[str, Any] | None:
        row = next(
            (r for r in self.rows.values() if r["id"] == kwargs["order_id"]), None
        )
        if row is None or row["status"] not in ("pending", "expired"):
            return None
        row["status"] = "paid"
        row["channel_order_no"] = kwargs["channel_order_no"]
        row["paid_at"] = kwargs["paid_at"]
        row["callback_payload"] = kwargs["callback_payload"]
        row["grant_expires_at"] = kwargs["grant_expires_at"]
        # 与 PG 实现同一事务语义：订单与会员权益同生共死
        if self.users is not None:
            self.users.apply_membership(
                kwargs["user_id"],
                kwargs["new_membership_tier"],
                kwargs["new_membership_expires_at"],
            )
        return dict(row)

    def close_order(self, *, order_id: int) -> dict[str, Any] | None:
        row = next((r for r in self.rows.values() if r["id"] == order_id), None)
        if row is None or row["status"] != "pending":
            return None
        row["status"] = "closed"
        return dict(row)


class FakeUsers:
    def __init__(self) -> None:
        self.users: dict[int, dict[str, Any]] = {}

    def add(
        self, user_id: int, tier: str = "free", expires_at: Any = None, email: str = ""
    ) -> None:
        self.users[user_id] = {
            "id": user_id,
            "membership_tier": tier,
            "membership_expires_at": expires_at,
            "email": email or f"user{user_id}@example.com",
        }

    def get_user_by_id(self, user_id: int) -> dict[str, Any] | None:
        user = self.users.get(user_id)
        return dict(user) if user is not None else None

    def apply_membership(self, user_id: int, tier: str, expires_at: Any) -> None:
        if user_id in self.users:
            self.users[user_id]["membership_tier"] = tier
            self.users[user_id]["membership_expires_at"] = expires_at


class FakeErrorEvents:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def insert_events(self, events: Any) -> int:
        self.events.extend(events)
        return len(self.events)


class FakeProvider:
    """可控渠道替身：默认已配置、下单返回 qr_code 指令、验签返回注入结果。"""

    def __init__(
        self,
        channel: str = "wechat_native",
        *,
        configured: bool = True,
        verified: VerifiedCallback | None = None,
        verify_error: Exception | None = None,
    ) -> None:
        self.channel = channel
        self._configured = configured
        self._verified = verified
        self._verify_error = verify_error
        # True 时验签返回 None（模拟「验签通过但非终态事件」，如 PayPal APPROVED 已自动 capture）
        self._verified_none = False
        self.create_calls: list[dict[str, Any]] = []

    def is_configured(self) -> bool:
        return self._configured

    def create_payment(
        self, *, order: dict[str, Any], notify_url: str, return_url: str | None, shopper_ip: str | None = None
    ) -> PaymentInstruction:
        if not self._configured:
            raise ProviderNotConfiguredError("fake channel not configured")
        self.create_calls.append(
            {
                "order_no": order["order_no"],
                "notify_url": notify_url,
                "return_url": return_url,
                "shopper_ip": shopper_ip,
            }
        )
        return PaymentInstruction(kind="qr_code", content=f"pay://{order['order_no']}")

    def verify_and_parse_callback(
        self, *, raw_body: bytes, headers: dict[str, str]
    ) -> VerifiedCallback | None:
        if self._verify_error is not None:
            raise self._verify_error
        if self._verified_none:
            return None
        assert self._verified is not None
        return self._verified

    def build_ack_response(self, *, ok: bool) -> JSONResponse:
        return JSONResponse({"ok": ok}, status_code=200 if ok else 400)

    def query_order(self, *, order: dict[str, Any]) -> str:
        return "unknown"


@pytest.fixture()
def harness(monkeypatch: pytest.MonkeyPatch) -> Any:
    """组装测试 app：路由 + 全替身依赖；返回各替身便于断言。"""
    from types import SimpleNamespace

    monkeypatch.setattr(settings, "payments_enabled", True)
    users = FakeUsers()
    users.add(7)
    users.add(8)
    orders = FakeOrders(users)
    error_events = FakeErrorEvents()
    provider = FakeProvider()
    providers = {
        "wechat_native": provider,
        "alipay_page": FakeProvider("alipay_page"),
        "overseas_redirect": FakeProvider("overseas_redirect"),
    }

    app = FastAPI()
    app.include_router(router, prefix="/api")
    # Legacy order/callback tests still exercise historical processing below.
    # Production rejects new purchases; dedicated tests restore the real gate.
    app.dependency_overrides[require_membership_purchase_enabled] = lambda: None
    app.dependency_overrides[RequireUser] = lambda: {"user_id": 7, "role": "user"}
    app.dependency_overrides[get_payment_order_repository] = lambda: orders
    app.dependency_overrides[get_user_account_repository] = lambda: users
    app.dependency_overrides[get_payment_providers] = lambda: providers
    app.dependency_overrides[get_error_event_repository] = lambda: error_events
    return SimpleNamespace(
        client=TestClient(app),
        app=app,
        users=users,
        orders=orders,
        provider=provider,
        providers=providers,
        error_events=error_events,
    )


# ── 特性门控 ────────────────────────────────────────────────────────────


def test_all_routes_404_when_payments_disabled(
    harness: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "payments_enabled", False)
    assert harness.client.get("/api/payments/plans").status_code == 404
    assert harness.client.post("/api/payments/orders", json={}).status_code == 404
    assert harness.client.get("/api/payments/orders").status_code == 404
    assert harness.client.get("/api/payments/orders/P1").status_code == 404
    assert (
        harness.client.post("/api/payments/callback/wechat_native", content=b"{}")
        .status_code
        == 404
    )


@pytest.mark.parametrize("signed_in", [False, True])
def test_new_membership_purchases_are_retired(harness: Any, signed_in: bool) -> None:
    harness.app.dependency_overrides.pop(require_membership_purchase_enabled)
    if not signed_in:
        harness.app.dependency_overrides.pop(RequireUser)
    for response in (
        harness.client.get("/api/payments/plans"),
        harness.client.post("/api/payments/orders", json={
            "plan_code": "member_monthly", "channel": "wechat_native",
        }),
    ):
        assert response.status_code == 410
        assert response.json() == {"detail": "membership_purchase_retired"}
    assert harness.orders.rows == {}
    assert harness.provider.create_calls == []


# ── plans ────────────────────────────────────────────────────────────────


def test_plans_are_public_and_pin_amounts(harness: Any) -> None:
    response = harness.client.get("/api/payments/plans")
    assert response.status_code == 200
    body = response.json()
    plans = {plan["code"]: plan for plan in body["plans"]}
    assert plans["member_monthly"]["amount_cents"] == 1900
    assert plans["member_monthly"]["months"] == 1
    assert plans["member_yearly"]["amount_cents"] == 15900
    assert plans["member_yearly"]["months"] == 12
    # 美元套餐与 CNY 目录并列返回；前端按界面语言拣选币种
    assert plans["member_monthly_usd"]["amount_cents"] == 490
    assert plans["member_monthly_usd"]["months"] == 1
    assert plans["member_yearly_usd"]["amount_cents"] == 1490
    assert plans["member_yearly_usd"]["months"] == 12
    for code in ("member_monthly", "member_yearly"):
        assert plans[code]["currency"] == "CNY"
    for code in ("member_monthly_usd", "member_yearly_usd"):
        assert plans[code]["currency"] == "USD"
    channels = {channel["channel"]: channel["available"] for channel in body["channels"]}
    assert set(channels) == {"wechat_native", "alipay_page", "overseas_redirect"}


def test_plans_reflect_channel_availability(harness: Any) -> None:
    harness.providers["overseas_redirect"]._configured = False
    body = harness.client.get("/api/payments/plans").json()
    channels = {channel["channel"]: channel["available"] for channel in body["channels"]}
    assert channels["overseas_redirect"] is False
    assert channels["wechat_native"] is True


@pytest.fixture()
def plan_override_reader() -> Any:
    """注入 payment_plan_overrides 假 reader；用例后复位，避免污染默认价钉。"""
    from backend.app.services.payments.plan_overrides import (
        configure_plan_overrides_reader,
    )
    from backend.tests.test_payment_plan_overrides import FakePlanOverridesReader

    reader = FakePlanOverridesReader({})
    configure_plan_overrides_reader(reader)
    yield reader
    configure_plan_overrides_reader(None)


def test_plans_endpoint_uses_runtime_overrides(harness: Any, plan_override_reader: Any) -> None:
    plan_override_reader.amounts.update(
        {"member_monthly": 2500, "member_yearly": 20000}
    )
    body = harness.client.get("/api/payments/plans").json()
    plans = {plan["code"]: plan for plan in body["plans"]}
    assert plans["member_monthly"]["amount_cents"] == 2500
    assert plans["member_yearly"]["amount_cents"] == 20000
    # 覆盖只换金额：时长/币种保持默认目录语义
    assert plans["member_monthly"]["months"] == 1
    assert plans["member_yearly"]["months"] == 12
    assert plans["member_monthly"]["currency"] == "CNY"
    assert plans["member_monthly_usd"]["amount_cents"] == 490
    assert plans["member_monthly_usd"]["currency"] == "USD"


def test_plans_endpoint_degrades_to_defaults_on_reader_failure(
    harness: Any, plan_override_reader: Any
) -> None:
    plan_override_reader.amounts["member_yearly"] = 20000
    plan_override_reader.fail = True
    body = harness.client.get("/api/payments/plans").json()
    plans = {plan["code"]: plan for plan in body["plans"]}
    assert plans["member_monthly"]["amount_cents"] == 1900
    assert plans["member_yearly"]["amount_cents"] == 15900


# ── 下单 ────────────────────────────────────────────────────────────────


def test_create_order_requires_auth(harness: Any) -> None:
    harness.app.dependency_overrides.pop(RequireUser)
    response = harness.client.post(
        "/api/payments/orders",
        json={"plan_code": "member_monthly", "channel": "wechat_native"},
    )
    assert response.status_code == 401


def test_create_order_rejects_unknown_plan_and_channel(harness: Any) -> None:
    response = harness.client.post(
        "/api/payments/orders",
        json={"plan_code": "member_lifetime", "channel": "wechat_native"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "unknown_plan"

    response = harness.client.post(
        "/api/payments/orders",
        json={"plan_code": "member_monthly", "channel": "paypal"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "unknown_channel"


def test_create_order_rejects_plan_channel_currency_mismatch(harness: Any) -> None:
    """币种 × 渠道兼容矩阵服务端收口：CNY 单禁走海外槽，USD 单禁走国内渠道。"""
    response = harness.client.post(
        "/api/payments/orders",
        json={"plan_code": "member_monthly", "channel": "overseas_redirect"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "plan_channel_currency_mismatch"

    for channel in ("wechat_native", "alipay_page"):
        response = harness.client.post(
            "/api/payments/orders",
            json={"plan_code": "member_monthly_usd", "channel": channel},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "plan_channel_currency_mismatch"
    # 错配零落单：仓储一行未写
    assert harness.orders.rows == {}


def test_create_order_503_when_channel_not_configured(harness: Any) -> None:
    harness.providers["overseas_redirect"]._configured = False
    response = harness.client.post(
        "/api/payments/orders",
        json={"plan_code": "member_monthly_usd", "channel": "overseas_redirect"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "payment_channel_not_configured"


def test_create_order_usd_overseas_happy_path(harness: Any) -> None:
    """USD 套餐 × 海外槽：订单按 USD 金额快照，notify_url 指海外回调端点。"""
    response = harness.client.post(
        "/api/payments/orders",
        json={"plan_code": "member_yearly_usd", "channel": "overseas_redirect"},
    )
    assert response.status_code == 200
    body = response.json()
    order = body["order"]
    assert order["plan_code"] == "member_yearly_usd"
    assert order["amount_cents"] == 1490
    assert order["currency"] == "USD"
    assert order["status"] == "pending"
    call = harness.providers["overseas_redirect"].create_calls[0]
    assert call["notify_url"].endswith("/api/payments/callback/overseas_redirect")


def test_create_order_happy_path_returns_instruction(harness: Any) -> None:
    response = harness.client.post(
        "/api/payments/orders",
        json={"plan_code": "member_yearly", "channel": "wechat_native"},
    )
    assert response.status_code == 200
    body = response.json()
    order = body["order"]
    assert order["order_no"].startswith("P")
    assert order["plan_code"] == "member_yearly"
    assert order["amount_cents"] == 15900
    assert order["status"] == "pending"
    assert body["instruction"]["kind"] == "qr_code"
    assert body["instruction"]["content"].endswith(order["order_no"])
    # notify_url 指向本单渠道回调端点
    call = harness.provider.create_calls[0]
    assert call["notify_url"].endswith("/api/payments/callback/wechat_native")
    # 响应不泄露内部列
    assert "callback_payload" not in order
    assert "idempotency_key" not in order


def test_create_order_snapshots_override_price(
    harness: Any, plan_override_reader: Any
) -> None:
    """运行时调价后下单：订单行按生效价快照（买家付其所见）。"""
    plan_override_reader.amounts.update(
        {"member_monthly": 2500, "member_yearly": 20000}
    )
    response = harness.client.post(
        "/api/payments/orders",
        json={"plan_code": "member_yearly", "channel": "wechat_native"},
    )
    assert response.status_code == 200
    assert response.json()["order"]["amount_cents"] == 20000


def test_create_order_idempotency_key_returns_existing_order(harness: Any) -> None:
    first = harness.client.post(
        "/api/payments/orders",
        json={
            "plan_code": "member_monthly",
            "channel": "wechat_native",
            "idempotency_key": "checkout-abc",
        },
    ).json()
    second = harness.client.post(
        "/api/payments/orders",
        json={
            "plan_code": "member_monthly",
            "channel": "wechat_native",
            "idempotency_key": "checkout-abc",
        },
    ).json()
    assert second["order"]["order_no"] == first["order"]["order_no"]
    assert len(harness.orders.rows) == 1
    # 幂等命中也重新取支付指令（渠道侧按 order_no 幂等）
    assert len(harness.provider.create_calls) == 2


# ── 我的订单 ─────────────────────────────────────────────────────────────


def _create(harness: Any, plan: str = "member_monthly") -> dict[str, Any]:
    return harness.client.post(
        "/api/payments/orders", json={"plan_code": plan, "channel": "wechat_native"}
    ).json()["order"]


def test_list_my_orders_paginated_newest_first(harness: Any) -> None:
    first = _create(harness)
    second = _create(harness, "member_yearly")
    response = harness.client.get("/api/payments/orders?page=1&page_size=1")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert body["items"][0]["order_no"] == second["order_no"]
    page_two = harness.client.get("/api/payments/orders?page=2&page_size=1").json()
    assert page_two["items"][0]["order_no"] == first["order_no"]


def test_get_order_detail_owner_only(harness: Any) -> None:
    order = _create(harness)
    detail = harness.client.get(f"/api/payments/orders/{order['order_no']}")
    assert detail.status_code == 200
    assert detail.json()["order_no"] == order["order_no"]

    # 非属主与不存在同形 404
    harness.app.dependency_overrides[RequireUser] = lambda: {"user_id": 8, "role": "user"}
    assert harness.client.get(f"/api/payments/orders/{order['order_no']}").status_code == 404
    assert harness.client.get("/api/payments/orders/PNOTEXIST").status_code == 404
