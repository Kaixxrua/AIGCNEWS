"""支付订单运营台账端点（ADR 0002）。

刻意不挂 payments_enabled 门控：开关关闭期间产生的订单（灰度/联调）与
历史台账仍需可查可补。补单（mark-paid）与用户侧回调共用同一发放入口
mark_paid_and_grant —— 恰好一次由仓储条件更新承载，Ops 重复补单是
幂等 200，不是错误。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Mapping

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backend.app.api.dependencies import (
    get_payment_config_admin_service,
    get_payment_order_repository,
    get_user_account_repository,
)
from backend.app.core.auth import RequireAdmin, extract_user_id
from backend.app.models.schema_payments import PaymentConfigRequest, PaymentConfigResponse
from backend.app.repositories.payment_order_repository import PaymentOrderRepository
from backend.app.repositories.user_account_repository import UserAccountRepository
from backend.app.services.payments.config_admin import PaymentConfigAdminService
from backend.app.services.payments.grant import mark_paid_and_grant
from backend.app.services.payments.orders import (
    ORDER_STATUS_CLOSED,
    ORDER_STATUS_PAID,
    ORDER_STATUSES,
    normalize_order_status,
)
from backend.app.services.payments.plans import UnknownPlanError, get_plan
from backend.app.services.payments.providers.base import VerifiedCallback

router = APIRouter()


@router.get("/ops/payments/config", response_model=PaymentConfigResponse, tags=["Ops"])
async def get_payment_config(
    _: dict = Depends(RequireAdmin),
    service: PaymentConfigAdminService = Depends(get_payment_config_admin_service),
) -> PaymentConfigResponse:
    """Return only masked payment configuration; never return credentials."""
    projection = await service.get_config()
    return PaymentConfigResponse.model_validate(projection, from_attributes=True)


@router.put("/ops/payments/config", response_model=PaymentConfigResponse, tags=["Ops"])
async def update_payment_config(
    request: PaymentConfigRequest,
    _: dict = Depends(RequireAdmin),
    service: PaymentConfigAdminService = Depends(get_payment_config_admin_service),
) -> PaymentConfigResponse:
    try:
        projection = await service.update_config(request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PaymentConfigResponse.model_validate(projection, from_attributes=True)


@router.delete("/ops/payments/config", response_model=PaymentConfigResponse, tags=["Ops"])
async def reset_payment_config(
    _: dict = Depends(RequireAdmin),
    service: PaymentConfigAdminService = Depends(get_payment_config_admin_service),
) -> PaymentConfigResponse:
    projection = await service.reset_config()
    return PaymentConfigResponse.model_validate(projection, from_attributes=True)


class OpsMarkPaidRequest(BaseModel):
    """补单：渠道已成功但回调未达（或骨架期人工收款确认）时的人工入账。"""

    # 缺省 = 操作时刻；naive 按 UTC 解释（与库内 timestamptz 口径一致）
    paid_at: datetime | None = None
    note: str = ""


def _to_admin_order(row: Mapping[str, Any]) -> dict[str, Any]:
    """台账视图：含 callback_payload 审计列与 email（Ops 专属）。"""
    return {
        "id": int(row["id"]),
        "order_no": row["order_no"],
        "user_id": int(row["user_id"]),
        "email": row.get("email"),
        "plan_code": row["plan_code"],
        "channel": row["channel"],
        "amount_cents": int(row["amount_cents"]),
        "currency": row["currency"],
        "status": normalize_order_status(row.get("status")),
        "channel_order_no": row.get("channel_order_no") or "",
        "idempotency_key": row.get("idempotency_key") or "",
        "callback_payload": row.get("callback_payload") or "",
        "paid_at": row.get("paid_at"),
        "grant_expires_at": row.get("grant_expires_at"),
        "expires_at": row["expires_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


@router.get("/ops/payments/orders", tags=["Ops"])
async def list_payment_orders_admin(
    status_filter: str | None = Query(default=None, alias="status"),
    channel: str | None = Query(default=None),
    plan_code: str | None = Query(default=None),
    email: str | None = Query(default=None),
    created_from: datetime | None = Query(default=None),
    created_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: dict = Depends(RequireAdmin),
    orders: PaymentOrderRepository = Depends(get_payment_order_repository),
) -> dict[str, Any]:
    """台账筛选 + 分页；status 过滤值 fail-closed（未知值 400）。"""
    if status_filter is not None and status_filter not in ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="unknown_status")
    rows, total = await asyncio.to_thread(
        orders.list_orders_admin,
        status=status_filter,
        channel=channel or None,
        plan_code=plan_code or None,
        email=email or None,
        created_from=created_from,
        created_to=created_to,
        page=page,
        page_size=page_size,
    )
    return {
        "items": [_to_admin_order(row) for row in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/ops/payments/orders/{order_no}", tags=["Ops"])
async def get_payment_order_admin(
    order_no: str,
    _: dict = Depends(RequireAdmin),
    orders: PaymentOrderRepository = Depends(get_payment_order_repository),
    users: UserAccountRepository = Depends(get_user_account_repository),
) -> dict[str, Any]:
    """单订单台账详情：含 callback_payload 审计列与用户邮箱。"""
    row = await asyncio.to_thread(orders.get_order_by_order_no, order_no)
    if row is None:
        raise HTTPException(status_code=404, detail="order_not_found")
    user = await asyncio.to_thread(users.get_user_by_id, int(row["user_id"]))
    detail = dict(row)
    detail["email"] = user.get("email") if user else None
    return _to_admin_order(detail)


@router.post("/ops/payments/orders/{order_no}/mark-paid", tags=["Ops"])
async def mark_payment_order_paid(
    order_no: str,
    body: OpsMarkPaidRequest,
    admin: dict = Depends(RequireAdmin),
    orders: PaymentOrderRepository = Depends(get_payment_order_repository),
    users: UserAccountRepository = Depends(get_user_account_repository),
) -> dict[str, Any]:
    """人工补单入账：与用户侧回调同一 mark_paid_and_grant 入口。

    已 paid → 幂等 200；closed 吸态 → 409（人工退款流程，绝不自动发放）。
    """
    row = await asyncio.to_thread(orders.get_order_by_order_no, order_no)
    if row is None:
        raise HTTPException(status_code=404, detail="order_not_found")
    order_status = normalize_order_status(row.get("status"))
    if order_status == ORDER_STATUS_PAID:
        return {"order": _to_admin_order(row), "granted": False, "note": "already_paid"}
    if order_status == ORDER_STATUS_CLOSED:
        raise HTTPException(status_code=409, detail="order_closed")

    paid_at = body.paid_at or datetime.now(timezone.utc)
    if paid_at.tzinfo is None:
        paid_at = paid_at.replace(tzinfo=timezone.utc)
    verified = VerifiedCallback(
        order_no=str(row["order_no"]),
        channel_order_no=str(row.get("channel_order_no") or "") or (
            f"ops-mark-paid:{extract_user_id(admin)}"
        ),
        amount_cents=int(row["amount_cents"]),
        currency=str(row["currency"]),
        paid_at=paid_at,
    )
    try:
        plan = get_plan(row["plan_code"])
    except UnknownPlanError as exc:
        raise HTTPException(status_code=422, detail="unknown_plan_on_order") from exc
    audit_payload = json.dumps(
        {
            "source": "ops_mark_paid",
            "admin_user_id": extract_user_id(admin),
            "note": body.note,
        },
        ensure_ascii=False,
    )
    result = await asyncio.to_thread(
        mark_paid_and_grant,
        orders=orders,
        users=users,
        order=row,
        verified=verified,
        plan=plan,
        now=datetime.now(timezone.utc),
        callback_payload=audit_payload,
    )
    updated = await asyncio.to_thread(orders.get_order_by_order_no, order_no)
    return {
        "order": _to_admin_order(updated) if updated else None,
        "granted": result.granted,
        "note": result.note,
        "new_expires_at": (
            result.new_expires_at.isoformat() if result.new_expires_at else None
        ),
    }


@router.post("/ops/payments/orders/{order_no}/close", tags=["Ops"])
async def close_payment_order(
    order_no: str,
    _: dict = Depends(RequireAdmin),
    orders: PaymentOrderRepository = Depends(get_payment_order_repository),
) -> dict[str, Any]:
    """人工关单：仅 pending → closed；终态（paid/expired/closed）一律 409。"""
    row = await asyncio.to_thread(orders.get_order_by_order_no, order_no)
    if row is None:
        raise HTTPException(status_code=404, detail="order_not_found")
    closed = await asyncio.to_thread(orders.close_order, order_id=int(row["id"]))
    if closed is None:
        raise HTTPException(status_code=409, detail="order_not_closable")
    return {"order": _to_admin_order(closed)}
