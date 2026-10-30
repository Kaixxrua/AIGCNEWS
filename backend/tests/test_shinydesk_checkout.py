"""闪光工坊激活码 PayPal 收单契约测试（真实 PayPalProvider + 有状态 PayPal/授权服务替身）。

钉住：
- 门控：总开关关 404；PayPal 或授权服务未配置 → available=false / 下单 503；
- 下单报文：9.99 USD、custom_id=SD 单号、商品名/品牌/NO_SHIPPING、回跳带 lang=en&order；
- 回跳 confirm 与 webhook（APPROVED / COMPLETED）两条入口恰好发一个码，重复回调同码；
- 伪造回调（验签 FAILURE / 缺头）、金额不对、币种不对、单号漂移一律拒绝且零发码；
- 授权服务故障停在 processing，恢复后同码补发；邮件只发一次；
- 退款/冲正自动作废，争议只标记；找回页按单号或交易号 + 付款邮箱，失败计数锁定；
- 会员 PayPal 订单的回调不受分流影响。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_shinydesk
from backend.app.api.dependencies import (
    get_error_event_repository,
    get_payment_order_repository,
    get_payment_providers,
    get_user_account_repository,
)
from backend.app.api.feature_gates import require_membership_purchase_enabled
from backend.app.api.routes_payments import router as payments_router
from backend.app.core.auth import RequireAdmin, RequireUser
from backend.app.core.config import settings
from backend.app.repositories.shinydesk_order_repository import InMemoryShinyDeskOrderRepository
from backend.app.services.shinydesk.license_client import ShinyDeskLicenseClient
from backend.tests.shinydesk_fakes import LICENSE_BASE, LICENSE_KEY, LICENSE_KEY_ID, FakeLicenseApi, FakePayPal
from backend.tests.test_payments_api import FakeErrorEvents, FakeOrders, FakeProvider, FakeUsers

SITE = "https://aigcnews.test/api/shiny-downloads/"


@pytest.fixture()
def shop(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(settings, "payments_enabled", True)
    monkeypatch.setenv("SHINYDESK_CHECKOUT_ENABLED", "1")
    monkeypatch.setenv("SHINYDESK_SITE_URL", SITE)
    paypal = FakePayPal()
    license_api = FakeLicenseApi()
    client = ShinyDeskLicenseClient(base_url=LICENSE_BASE, key_id=LICENSE_KEY_ID, secret=LICENSE_KEY, transport=license_api.transport())
    state = SimpleNamespace(license_client=client)
    monkeypatch.setattr(routes_shinydesk, "build_license_client", lambda config: state.license_client)
    sent: list[tuple[str, str, str]] = []
    state.mailer_enabled = True

    async def send_plain(to: str, subject: str, body: str) -> None:
        sent.append((to, subject, body))

    mailer_dependency = routes_shinydesk.get_shinydesk_mailer  # 路由 Depends 持有的原函数
    monkeypatch.setattr(routes_shinydesk, "get_shinydesk_mailer", lambda request: send_plain if state.mailer_enabled else None)

    users = FakeUsers()
    users.add(7)
    member_orders = FakeOrders(users)
    error_events = FakeErrorEvents()
    providers = {
        "wechat_native": FakeProvider("wechat_native"),
        "alipay_page": FakeProvider("alipay_page"),
        "overseas_redirect": paypal.provider(),
    }
    app = FastAPI()
    app.include_router(payments_router, prefix="/api")
    app.include_router(routes_shinydesk.router, prefix="/api")
    app.include_router(routes_shinydesk.ops_router, prefix="/api")
    app.state.shinydesk_orders = InMemoryShinyDeskOrderRepository()
    # 新会员购买已下线（410）；回归用例仍需造一笔会员订单来验证共用回调照常开通。
    app.dependency_overrides[require_membership_purchase_enabled] = lambda: None
    app.dependency_overrides[get_payment_providers] = lambda: providers
    app.dependency_overrides[get_error_event_repository] = lambda: error_events
    app.dependency_overrides[get_payment_order_repository] = lambda: member_orders
    app.dependency_overrides[get_user_account_repository] = lambda: users
    app.dependency_overrides[RequireUser] = lambda: {"user_id": 7, "role": "user"}
    app.dependency_overrides[RequireAdmin] = lambda: {"user_id": 1, "role": "admin"}
    app.dependency_overrides[routes_shinydesk.get_shinydesk_license_client] = lambda: state.license_client
    app.dependency_overrides[mailer_dependency] = lambda: send_plain if state.mailer_enabled else None
    return SimpleNamespace(
        client=TestClient(app),
        app=app,
        paypal=paypal,
        license_api=license_api,
        orders=app.state.shinydesk_orders,
        member_orders=member_orders,
        users=users,
        error_events=error_events,
        providers=providers,
        sent=sent,
        state=state,
    )


def _create(shop: Any) -> dict[str, Any]:
    response = shop.client.post("/api/shinydesk/orders", json={})
    assert response.status_code == 200, response.text
    body = response.json()
    body["paypal_order_id"] = body["approve_url"].rsplit("token=", 1)[1]
    return body


def _confirm(shop: Any, order: dict[str, Any], **extra: Any):
    return shop.client.post(
        f"/api/shinydesk/orders/{order['order_no']}/confirm",
        json={"access_token": order["access_token"], "paypal_order_id": order["paypal_order_id"], **extra},
    )


def _webhook(shop: Any, event: dict[str, Any], *, genuine: bool = True):
    headers = shop.paypal.genuine() if genuine else shop.paypal.forged()
    return shop.client.post("/api/payments/callback/overseas_redirect", content=json.dumps(event).encode(), headers=headers)


def _row(shop: Any, order: dict[str, Any]) -> dict[str, Any]:
    return shop.orders.get_by_order_no(order["order_no"])


# ── 门控与下单 ───────────────────────────────────────────────────────────


def test_feature_flag_off_hides_every_public_route(shop: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHINYDESK_CHECKOUT_ENABLED", "0")
    assert shop.client.get("/api/shinydesk/checkout").status_code == 404
    assert shop.client.post("/api/shinydesk/orders", json={}).status_code == 404
    assert shop.client.post("/api/shinydesk/lookup", json={"reference": "x", "email": "a@b.c"}).status_code == 404


def test_checkout_status_reports_price_and_availability(shop: Any) -> None:
    body = shop.client.get("/api/shinydesk/checkout").json()
    assert body["available"] is True
    assert (body["amount_cents"], body["currency"]) == (999, "USD")
    assert body["terms"] == {"permanent": True, "desktop_devices": 1, "android_devices": 1, "concurrent_jobs": 2}
    shop.state.license_client = None
    assert shop.client.get("/api/shinydesk/checkout").json()["available"] is False
    assert shop.client.post("/api/shinydesk/orders", json={}).json()["detail"] == "checkout_unavailable"


def test_checkout_unavailable_when_overseas_slot_is_not_paypal(shop: Any) -> None:
    shop.providers["overseas_redirect"] = FakeProvider("overseas_redirect")
    assert shop.client.get("/api/shinydesk/checkout").json()["available"] is False
    assert shop.client.post("/api/shinydesk/orders", json={}).status_code == 503


def test_create_order_sends_fixed_usd_price_and_binds_paypal_order(shop: Any) -> None:
    order = _create(shop)
    assert order["order_no"].startswith("SD") and len(order["order_no"]) == 24
    assert (order["amount_cents"], order["currency"]) == (999, "USD")
    request = shop.paypal.orders[order["paypal_order_id"]]["request"]
    unit = request["purchase_units"][0]
    assert unit["amount"] == {"currency_code": "USD", "value": "9.99"}
    assert unit["custom_id"] == order["order_no"]
    assert unit["description"].startswith("ShinyDesk license")
    context = request["application_context"]
    assert context["brand_name"] == "ShinyDesk"
    assert context["shipping_preference"] == "NO_SHIPPING"
    assert context["return_url"] == f"{SITE}?lang=en&order={order['order_no']}"
    row = _row(shop, order)
    assert row["status"] == "pending" and row["paypal_order_id"] == order["paypal_order_id"]
    assert row["access_token_hash"] != order["access_token"]  # 只存哈希


# ── 回跳 confirm 主流程 ─────────────────────────────────────────────────


def test_confirm_before_approval_changes_nothing(shop: Any) -> None:
    order = _create(shop)
    body = _confirm(shop, order).json()
    assert body["status"] == "pending" and body["payment_state"] == "ORDER_NOT_APPROVED"
    assert body["license_code"] is None and shop.license_api.issued == 0


def test_confirm_after_approval_issues_one_code_and_emails_it(shop: Any) -> None:
    order = _create(shop)
    shop.paypal.approve(order["paypal_order_id"])
    body = _confirm(shop, order).json()
    assert body["status"] == "fulfilled"
    assert body["license_code"].startswith("PB-") and len(body["license_code"]) == 43
    assert body["payer_email"] == "B***@Example.com"
    assert body["email_status"] == "sent"
    assert len(shop.license_api.purchases) == 1
    assert [to for to, _, _ in shop.sent] == ["Buyer@Example.com"]
    assert body["license_code"] in shop.sent[0][2] and order["order_no"] in shop.sent[0][2]
    # 重复 confirm（刷新页面）：同码、不再调授权服务、不再发邮件
    again = _confirm(shop, order).json()
    assert again["license_code"] == body["license_code"]
    assert shop.license_api.issued == 1 and len(shop.sent) == 1
    status = shop.client.post(f"/api/shinydesk/orders/{order['order_no']}/status", json={"access_token": order["access_token"]}).json()
    assert status["license_code"] == body["license_code"]


def test_wrong_access_token_or_unknown_order_is_404(shop: Any) -> None:
    order = _create(shop)
    shop.paypal.approve(order["paypal_order_id"])
    assert _confirm(shop, {**order, "access_token": "nope"}).status_code == 404
    assert shop.client.post("/api/shinydesk/orders/SD20261030000000ABCDEF12/status", json={"access_token": "x"}).status_code == 404
    assert shop.license_api.issued == 0


def test_confirm_rejects_paypal_order_id_of_another_order(shop: Any) -> None:
    first, second = _create(shop), _create(shop)
    shop.paypal.approve(second["paypal_order_id"])
    response = _confirm(shop, {**first, "paypal_order_id": second["paypal_order_id"]})
    assert response.status_code == 422 and response.json()["detail"] == "paypal_order_mismatch"
    assert shop.license_api.issued == 0


# ── webhook 主流程与幂等 ─────────────────────────────────────────────────


def test_webhooks_alone_fulfil_and_duplicates_return_same_code(shop: Any) -> None:
    order = _create(shop)
    shop.paypal.approve(order["paypal_order_id"])
    assert _webhook(shop, shop.paypal.approved_event(order["paypal_order_id"])).status_code == 200
    row = _row(shop, order)
    assert row["status"] == "fulfilled" and row["email_status"] == "sent"
    code = row["license_code"]
    for _ in range(3):
        assert _webhook(shop, shop.paypal.completed_event(order["paypal_order_id"])).status_code == 200
        assert _webhook(shop, shop.paypal.approved_event(order["paypal_order_id"])).status_code == 200
    assert _row(shop, order)["license_code"] == code
    assert len(shop.license_api.purchases) == 1 and shop.license_api.issued == 1
    assert len(shop.sent) == 1
    # 买家此后回到页面：同一个码
    assert _confirm(shop, order).json()["license_code"] == code


def test_completed_webhook_without_page_return_fulfils(shop: Any) -> None:
    order = _create(shop)
    shop.paypal.approve(order["paypal_order_id"])
    # PayPal 自己完成了 capture（例如买家关掉了回跳页、APPROVED 事件丢失）
    shop.provider = shop.providers["overseas_redirect"]
    shop.provider.capture_order_details(paypal_order_id=order["paypal_order_id"], request_id=order["order_no"])
    assert _webhook(shop, shop.paypal.completed_event(order["paypal_order_id"])).status_code == 200
    row = _row(shop, order)
    assert row["status"] == "fulfilled" and row["payer_email"] == "Buyer@Example.com"


def test_forged_webhooks_are_rejected_without_side_effects(shop: Any) -> None:
    order = _create(shop)
    shop.paypal.approve(order["paypal_order_id"])
    response = _webhook(shop, shop.paypal.approved_event(order["paypal_order_id"]), genuine=False)
    assert response.status_code == 400
    missing = shop.client.post(
        "/api/payments/callback/overseas_redirect",
        content=json.dumps(shop.paypal.approved_event(order["paypal_order_id"])).encode(),
        headers={"content-type": "application/json"},
    )
    assert missing.status_code == 400
    # 伪造事件不触发 capture，订单保持 pending、零发码
    assert shop.paypal.orders[order["paypal_order_id"]]["status"] == "APPROVED"
    assert _row(shop, order)["status"] == "pending" and shop.license_api.issued == 0


@pytest.mark.parametrize(
    ("override", "label"),
    [({"value": "0.99", "currency_code": "USD"}, "amount"), ({"value": "9.99", "currency_code": "EUR"}, "currency"),
     ({"value": "99.90", "currency_code": "USD"}, "amount-high")],
)
def test_amount_or_currency_mismatch_is_rejected(shop: Any, override: dict[str, str], label: str) -> None:
    order = _create(shop)
    shop.paypal.approve(order["paypal_order_id"])
    shop.paypal.capture_override[order["paypal_order_id"]] = override
    response = _confirm(shop, order)
    assert response.status_code == 422 and response.json()["detail"] == "amount_mismatch", label
    # 同一笔再经 webhook 送达也被拒
    assert _webhook(shop, shop.paypal.completed_event(order["paypal_order_id"])).status_code == 422
    assert _row(shop, order)["status"] == "pending"
    assert shop.license_api.issued == 0 and shop.sent == []
    assert any(event.exception_type == "PaymentAmountMismatch" for event in shop.error_events.events)


def test_pending_capture_waits_without_issuing(shop: Any) -> None:
    order = _create(shop)
    shop.paypal.approve(order["paypal_order_id"])
    shop.paypal.capture_status = "PENDING"
    assert _confirm(shop, order).json()["status"] == "pending"
    assert shop.license_api.issued == 0


def test_webhook_custom_id_mismatch_is_rejected(shop: Any) -> None:
    first, second = _create(shop), _create(shop)
    shop.paypal.approve(second["paypal_order_id"])
    event = shop.paypal.approved_event(second["paypal_order_id"])
    event["resource"]["purchase_units"][0]["custom_id"] = first["order_no"]  # 指向别的单
    assert _webhook(shop, event).status_code == 422
    assert _row(shop, first)["status"] == "pending" and shop.license_api.issued == 0


# ── 授权服务故障与恢复 ───────────────────────────────────────────────────


def test_license_outage_keeps_order_paid_and_retries_with_same_code(shop: Any) -> None:
    order = _create(shop)
    shop.paypal.approve(order["paypal_order_id"])
    shop.license_api.down = True
    body = _confirm(shop, order).json()
    assert body["status"] == "processing" and body["license_code"] is None
    assert "unreachable" in _row(shop, order)["last_error"]
    shop.license_api.down = False
    status = shop.client.post(f"/api/shinydesk/orders/{order['order_no']}/status", json={"access_token": order["access_token"]}).json()
    assert status["status"] == "fulfilled" and status["license_code"].startswith("PB-")
    assert len(shop.license_api.purchases) == 1


def test_license_issue_lost_response_replays_same_code(shop: Any) -> None:
    order = _create(shop)
    shop.paypal.approve(order["paypal_order_id"])
    # 授权服务已发码但本站没收到响应：下次 issue 必须拿回同一个码
    first = shop.state.license_client.issue(paypal_order_id=order["paypal_order_id"], order_no=order["order_no"])
    body = _confirm(shop, order).json()
    assert body["license_code"] == first.code


def test_email_skipped_when_smtp_missing_but_code_still_shown(shop: Any) -> None:
    shop.state.mailer_enabled = False
    order = _create(shop)
    shop.paypal.approve(order["paypal_order_id"])
    body = _confirm(shop, order).json()
    assert body["status"] == "fulfilled" and body["email_status"] == "skipped" and body["license_code"]


# ── 退款 / 冲正 / 争议 ───────────────────────────────────────────────────


def _paid(shop: Any) -> dict[str, Any]:
    order = _create(shop)
    shop.paypal.approve(order["paypal_order_id"])
    order["code"] = _confirm(shop, order).json()["license_code"]
    return order


@pytest.mark.parametrize(("event_type", "reason"), [("PAYMENT.CAPTURE.REFUNDED", "refund"), ("PAYMENT.CAPTURE.REVERSED", "reversal")])
def test_refund_or_reversal_revokes_code(shop: Any, event_type: str, reason: str) -> None:
    order = _paid(shop)
    assert _webhook(shop, shop.paypal.refunded_event(order["paypal_order_id"], event_type)).status_code == 200
    row = _row(shop, order)
    assert row["status"] == "revoked" and row["revoke_reason"] == reason
    assert shop.license_api.purchases[order["paypal_order_id"]]["revoked"] is True
    # 页面不再显示码；重复退款事件幂等
    shown = _confirm(shop, order).json()
    assert shown["status"] == "revoked" and shown["license_code"] is None
    assert _webhook(shop, shop.paypal.refunded_event(order["paypal_order_id"], event_type)).status_code == 200


def test_refund_while_license_service_down_asks_paypal_to_retry(shop: Any) -> None:
    order = _paid(shop)
    shop.license_api.down = True
    assert _webhook(shop, shop.paypal.refunded_event(order["paypal_order_id"])).status_code == 503
    assert _row(shop, order)["status"] == "fulfilled"
    shop.license_api.down = False
    assert _webhook(shop, shop.paypal.refunded_event(order["paypal_order_id"])).status_code == 200
    assert _row(shop, order)["status"] == "revoked"


def test_dispute_is_flagged_not_revoked(shop: Any) -> None:
    order = _paid(shop)
    assert _webhook(shop, shop.paypal.dispute_event(order["paypal_order_id"])).status_code == 200
    row = _row(shop, order)
    assert row["status"] == "fulfilled" and row["dispute_status"] == "OPEN"
    assert shop.license_api.purchases[order["paypal_order_id"]]["revoked"] is False
    assert any(event.exception_type == "ShinyDeskDispute" for event in shop.error_events.events)
    # 人工决定作废
    response = shop.client.post(f"/api/ops/shinydesk/orders/{order['order_no']}/revoke", json={"reason": "dispute"})
    assert response.status_code == 200 and response.json()["status"] == "revoked"
    assert shop.license_api.purchases[order["paypal_order_id"]]["revoked"] is True


# ── 找回 ─────────────────────────────────────────────────────────────────


def test_lookup_by_order_no_or_transaction_id_with_payer_email(shop: Any) -> None:
    order = _paid(shop)
    by_order = shop.client.post("/api/shinydesk/lookup", json={"reference": order["order_no"].lower(), "email": " buyer@example.COM "})
    assert by_order.status_code == 200 and by_order.json()["license_code"] == order["code"]
    capture_id = _row(shop, order)["paypal_capture_id"]
    by_txn = shop.client.post("/api/shinydesk/lookup", json={"reference": capture_id, "email": "buyer@example.com"})
    assert by_txn.json()["license_code"] == order["code"]


def test_lookup_wrong_email_is_404_and_locks_after_ten_failures(shop: Any) -> None:
    order = _paid(shop)
    for _ in range(10):
        response = shop.client.post("/api/shinydesk/lookup", json={"reference": order["order_no"], "email": "thief@example.com"})
        assert response.status_code == 404
    locked = shop.client.post("/api/shinydesk/lookup", json={"reference": order["order_no"], "email": "buyer@example.com"})
    assert locked.status_code == 404
    unknown = shop.client.post("/api/shinydesk/lookup", json={"reference": "SD20261030000000ABCDEF12", "email": "buyer@example.com"})
    assert unknown.status_code == 404


# ── Ops ──────────────────────────────────────────────────────────────────


def test_ops_list_retry_and_resend(shop: Any) -> None:
    order = _create(shop)
    shop.paypal.approve(order["paypal_order_id"])
    shop.providers["overseas_redirect"].capture_order_details(paypal_order_id=order["paypal_order_id"], request_id=order["order_no"])
    # 回跳与 webhook 都丢了：Ops retry 查 PayPal 订单补落账
    retried = shop.client.post(f"/api/ops/shinydesk/orders/{order['order_no']}/retry").json()
    assert retried["status"] == "fulfilled" and "access_token_hash" not in retried
    listed = shop.client.get("/api/ops/shinydesk/orders", params={"q": "buyer@example.com"}).json()
    assert listed["total"] == 1 and listed["items"][0]["order_no"] == order["order_no"]
    resent = shop.client.post(f"/api/ops/shinydesk/orders/{order['order_no']}/resend-email").json()
    assert resent["email_status"] == "sent" and len(shop.sent) == 2


def test_ops_routes_require_admin(shop: Any) -> None:
    shop.app.dependency_overrides.pop(RequireAdmin)
    assert shop.client.get("/api/ops/shinydesk/orders").status_code in (401, 403)


# ── 会员订单不受影响 ─────────────────────────────────────────────────────


def test_membership_paypal_webhook_still_grants_through_shared_callback(shop: Any) -> None:
    order = shop.client.post(
        "/api/payments/orders", json={"plan_code": "member_monthly_usd", "channel": "overseas_redirect"}
    ).json()["order"]
    paypal_order_id = next(iter(shop.paypal.orders))
    assert shop.paypal.orders[paypal_order_id]["custom_id"] == order["order_no"]
    request = shop.paypal.orders[paypal_order_id]["request"]
    assert request["application_context"]["brand_name"] == "AIGC Radar"  # 会员报文不变
    assert "shipping_preference" not in request["application_context"]
    shop.paypal.approve(paypal_order_id)
    assert _webhook(shop, shop.paypal.approved_event(paypal_order_id)).status_code == 200  # 原逻辑：capture 后返回 None
    assert _webhook(shop, shop.paypal.completed_event(paypal_order_id)).status_code == 200
    assert shop.member_orders.rows[order["order_no"]]["status"] == "paid"
    assert shop.users.users[7]["membership_tier"] == "member"
    assert shop.license_api.issued == 0 and len(shop.orders.list_orders(query="", page=1, page_size=10)[0]) == 0


def test_flag_off_leaves_shinydesk_webhooks_to_membership_logic(shop: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    order = _create(shop)
    shop.paypal.approve(order["paypal_order_id"])
    shop.providers["overseas_redirect"].capture_order_details(paypal_order_id=order["paypal_order_id"], request_id=order["order_no"])
    monkeypatch.setenv("SHINYDESK_CHECKOUT_ENABLED", "0")
    response = _webhook(shop, shop.paypal.completed_event(order["paypal_order_id"]))
    assert response.status_code == 404  # 会员表里没有 SD 单：与未知单号同形，PayPal 稍后重发
    assert shop.license_api.issued == 0
