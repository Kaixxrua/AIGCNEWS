"""ShinyDesk 订单落账与发码（同步函数，路由层 asyncio.to_thread 调用）。

三条入口汇到同一个 fulfill_from_paypal_order：
1. 回跳页 confirm：服务端 capture（PayPal 订单原文来自我们自己 OAuth 的 API 调用）；
2. webhook CHECKOUT.ORDER.APPROVED：验签后服务端 capture；
3. webhook PAYMENT.CAPTURE.COMPLETED：验签后 GET 订单原文（取付款邮箱）。

校验链（fail-closed）：custom_id = 本站单号 → PayPal 订单号与已绑定的一致 →
capture.status = COMPLETED → 金额/币种与订单快照一致 → 条件 UPDATE pending→paid →
授权服务器发码（幂等键 = PayPal 订单号）→ 条件 UPDATE paid→fulfilled。
发码失败时订单停在 paid，后续任一入口（重发 webhook、页面轮询 status、Ops retry）
都会再次发码并拿到同一个码。

退款/冲正（PAYMENT.CAPTURE.REFUNDED / REVERSED）自动作废码；争议
（CUSTOMER.DISPUTE.*）只记录状态 + error_events 告警，由人工决定是否作废。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from backend.app.repositories.error_event_repository import ErrorEventInsert, ErrorEventRepository
from backend.app.repositories.shinydesk_order_repository import ShinyDeskOrderRepository
from backend.app.services.payments.providers.base import CallbackVerificationError
from backend.app.services.shinydesk.license_client import (
    LicenseServiceError,
    LicenseServiceRejected,
    ShinyDeskLicenseClient,
)
from backend.app.services.shinydesk.product import is_shinydesk_order_no

logger = logging.getLogger(__name__)

_PAYPAL_ID_RE = re.compile(r"[A-Z0-9]{8,40}\Z")
_CAPTURE_LINK_RE = re.compile(r"/v2/payments/captures/([A-Z0-9]{8,40})\Z")


class ShinyDeskMismatch(RuntimeError):
    """PayPal 侧事实与订单快照不符（单号/金额/币种/PayPal 单号漂移）：422 + error_events。"""


@dataclass(frozen=True)
class CaptureFacts:
    paypal_order_id: str
    order_no: str
    capture_id: str
    capture_status: str
    amount_cents: int
    currency: str
    payer_email: str
    paid_at: datetime | None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_access_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def token_matches(row: Mapping[str, Any], token: object) -> bool:
    if not isinstance(token, str) or not token or len(token) > 200:
        return False
    return secrets.compare_digest(str(row["access_token_hash"]), hash_token(token))


def is_paypal_id(value: object) -> bool:
    return isinstance(value, str) and bool(_PAYPAL_ID_RE.fullmatch(value))


def _amount_to_cents(value: object) -> int:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CallbackVerificationError("invalid paypal amount") from exc
    cents = amount * 100
    if not amount.is_finite() or amount <= 0 or cents != cents.to_integral_value():
        raise CallbackVerificationError("invalid paypal amount")
    return int(cents)


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def capture_facts(order_payload: Mapping[str, Any]) -> CaptureFacts:
    """PayPal v2 订单原文 → 落账事实；结构不合法抛 CallbackVerificationError。"""
    paypal_order_id = order_payload.get("id")
    if not is_paypal_id(paypal_order_id):
        raise CallbackVerificationError("paypal order missing id")
    units = order_payload.get("purchase_units")
    if not isinstance(units, list) or len(units) != 1 or not isinstance(units[0], Mapping):
        raise CallbackVerificationError("paypal order must have exactly one purchase unit")
    unit = units[0]
    order_no = str(unit.get("custom_id") or unit.get("reference_id") or "")
    payer = order_payload.get("payer")
    payer_email = ""
    if isinstance(payer, Mapping) and isinstance(payer.get("email_address"), str):
        payer_email = payer["email_address"].strip()[:320]
    payments = unit.get("payments")
    captures = payments.get("captures") if isinstance(payments, Mapping) else None
    if not isinstance(captures, list) or not captures:
        status = str(order_payload.get("status") or "")
        return CaptureFacts(paypal_order_id, order_no, "", f"ORDER_{status}", 0, "", payer_email, None)
    if len(captures) != 1 or not isinstance(captures[0], Mapping):
        raise CallbackVerificationError("unexpected number of paypal captures")
    capture = captures[0]
    amount = capture.get("amount")
    if not isinstance(amount, Mapping) or not isinstance(amount.get("currency_code"), str):
        raise CallbackVerificationError("paypal capture missing amount")
    capture_id = capture.get("id")
    if not is_paypal_id(capture_id):
        raise CallbackVerificationError("paypal capture missing id")
    capture_order_no = str(capture.get("custom_id") or order_no)
    if capture_order_no != order_no:
        raise CallbackVerificationError("paypal capture custom_id differs from purchase unit")
    return CaptureFacts(
        paypal_order_id=paypal_order_id,
        order_no=order_no,
        capture_id=capture_id,
        capture_status=str(capture.get("status") or ""),
        amount_cents=_amount_to_cents(amount.get("value")),
        currency=amount["currency_code"].upper(),
        payer_email=payer_email,
        paid_at=_parse_time(capture.get("create_time")),
    )


def _alert(error_events: ErrorEventRepository, message: str, exception_type: str, level: str = "ERROR") -> None:
    try:
        error_events.insert_events(
            [ErrorEventInsert(level=level, logger_name="shinydesk.checkout", message=message, exception_type=exception_type)]
        )
    except Exception:  # 告警落库失败不能吞掉主流程
        logger.exception("[ShinyDesk] failed to record error event: %s", message)


def fulfill_from_paypal_order(
    *,
    orders: ShinyDeskOrderRepository,
    license_client: ShinyDeskLicenseClient | None,
    error_events: ErrorEventRepository,
    order: Mapping[str, Any],
    order_payload: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """按 PayPal 订单原文推进本站订单；返回最新订单行。可重复调用（幂等）。"""
    facts = capture_facts(order_payload)
    if facts.order_no != order["order_no"]:
        _alert(error_events, f"shinydesk order_no mismatch: ours={order['order_no']} paypal={facts.order_no} paypal_order={facts.paypal_order_id}", "ShinyDeskOrderMismatch")
        raise ShinyDeskMismatch("order_no_mismatch")
    bound = order.get("paypal_order_id")
    if bound and bound != facts.paypal_order_id:
        _alert(error_events, f"shinydesk paypal order drift: order_no={order['order_no']} bound={bound} got={facts.paypal_order_id}", "ShinyDeskOrderMismatch")
        raise ShinyDeskMismatch("paypal_order_mismatch")
    if facts.capture_status != "COMPLETED":
        # 未批准 / 待审核（PENDING）/ 拒付（DECLINED）：不落账，等 webhook 或买家重试。
        return dict(order)
    if facts.amount_cents != int(order["amount_cents"]) or facts.currency != str(order["currency"]).upper():
        _alert(
            error_events,
            f"shinydesk amount mismatch: order_no={order['order_no']} expected={order['amount_cents']}{order['currency']} got={facts.amount_cents}{facts.currency} capture={facts.capture_id}",
            "PaymentAmountMismatch",
        )
        raise ShinyDeskMismatch("amount_mismatch")

    current = dict(order)
    if current["status"] == "pending":
        paid = orders.mark_paid(
            order_id=int(current["id"]),
            paypal_order_id=facts.paypal_order_id,
            capture_id=facts.capture_id,
            payer_email=facts.payer_email,
            paid_at=facts.paid_at or now,
            callback_payload=json.dumps(order_payload, separators=(",", ":"), ensure_ascii=False),
        )
        current = paid or orders.get_by_order_no(str(order["order_no"])) or current
        if paid is None and current["status"] == "pending":
            _alert(error_events, f"shinydesk mark_paid conflict: order_no={order['order_no']} capture={facts.capture_id}", "ShinyDeskOrderMismatch")
            raise ShinyDeskMismatch("capture_conflict")
    elif current["status"] == "closed":
        _alert(error_events, f"shinydesk payment on closed order: order_no={order['order_no']} capture={facts.capture_id}", "PaymentOnClosedOrder")
        return current
    elif current.get("paypal_capture_id") and current["paypal_capture_id"] != facts.capture_id:
        _alert(error_events, f"shinydesk second capture: order_no={order['order_no']} first={current['paypal_capture_id']} second={facts.capture_id}", "ShinyDeskOrderMismatch")
        raise ShinyDeskMismatch("capture_conflict")

    if current["status"] == "paid":
        current = issue_license(orders=orders, license_client=license_client, error_events=error_events, order=current)
    return current


def issue_license(
    *,
    orders: ShinyDeskOrderRepository,
    license_client: ShinyDeskLicenseClient | None,
    error_events: ErrorEventRepository,
    order: Mapping[str, Any],
) -> dict[str, Any]:
    """paid → fulfilled；授权服务器失败时停在 paid 并记 last_error（下次入口重试）。"""
    if license_client is None:
        orders.record_error(order_id=int(order["id"]), error="license service not configured")
        _alert(error_events, f"shinydesk paid but license service not configured: order_no={order['order_no']}", "ShinyDeskIssueFailed")
        return dict(order)
    try:
        issued = license_client.issue(paypal_order_id=str(order["paypal_order_id"]), order_no=str(order["order_no"]))
    except LicenseServiceError as exc:
        orders.record_error(order_id=int(order["id"]), error=str(exc))
        level = "ERROR" if isinstance(exc, LicenseServiceRejected) else "WARNING"
        _alert(error_events, f"shinydesk license issue failed: order_no={order['order_no']} error={exc}", "ShinyDeskIssueFailed", level)
        return dict(order)
    if issued.revoked:
        # 授权服务器侧已作废（人工先在那边处理了退款）：本站同步为 revoked，绝不展示码。
        return orders.mark_revoked(order_id=int(order["id"]), reason="manual") or orders.get_by_order_no(str(order["order_no"])) or dict(order)
    fulfilled = orders.mark_fulfilled(order_id=int(order["id"]), license_code=issued.code, license_id=issued.license_id)
    return fulfilled or orders.get_by_order_no(str(order["order_no"])) or dict(order)


def revoke_order(
    *,
    orders: ShinyDeskOrderRepository,
    license_client: ShinyDeskLicenseClient | None,
    error_events: ErrorEventRepository,
    order: Mapping[str, Any],
    reason: str,
) -> dict[str, Any]:
    """作废：先让授权服务器停用码（失败抛 LicenseServiceError，调用方 5xx 等重试），再记本站状态。"""
    if order["status"] in ("paid", "fulfilled") and order.get("paypal_order_id"):
        if license_client is None:
            raise LicenseServiceError("license service not configured")
        try:
            license_client.revoke(paypal_order_id=str(order["paypal_order_id"]), reason=reason)
        except LicenseServiceRejected as exc:
            if exc.status_code != 404:  # 404：从未发过码（停在 paid），只改本站状态
                raise
    updated = orders.mark_revoked(order_id=int(order["id"]), reason=reason)
    if updated is not None:
        _alert(error_events, f"shinydesk license revoked: order_no={order['order_no']} reason={reason}", "ShinyDeskRevoked", "WARNING")
    return updated or orders.get_by_order_no(str(order["order_no"])) or dict(order)


# ── webhook 分流 ─────────────────────────────────────────────────────────


def event_order_no(event: Mapping[str, Any]) -> str:
    resource = event.get("resource")
    if not isinstance(resource, Mapping):
        return ""
    if event.get("event_type") == "CHECKOUT.ORDER.APPROVED":
        units = resource.get("purchase_units")
        if isinstance(units, list) and units and isinstance(units[0], Mapping):
            return str(units[0].get("custom_id") or units[0].get("reference_id") or "")
        return ""
    return str(resource.get("custom_id") or "")


def refunded_capture_id(resource: Mapping[str, Any]) -> str:
    """退款/冲正事件 → 被退的 capture id（links rel=up 指向 /v2/payments/captures/{id}）。"""
    links = resource.get("links")
    if isinstance(links, list):
        for link in links:
            if isinstance(link, Mapping) and link.get("rel") == "up":
                match = _CAPTURE_LINK_RE.search(str(link.get("href") or ""))
                if match:
                    return match.group(1)
    return ""


def disputed_capture_ids(resource: Mapping[str, Any]) -> list[str]:
    transactions = resource.get("disputed_transactions")
    if not isinstance(transactions, list):
        return []
    return [
        str(item["seller_transaction_id"])
        for item in transactions
        if isinstance(item, Mapping) and is_paypal_id(item.get("seller_transaction_id"))
    ]


def is_shinydesk_event_candidate(event: Mapping[str, Any]) -> bool:
    return is_shinydesk_order_no(event_order_no(event))
