"""支付收费骨架的用户侧路由与渠道回调端点（ADR 0002）。

整组路由挂 require_payments_enabled 门控：开关关闭时对外 404（与未部署
收费能力一致）。回调管线纪律：
  验签（原始字节，provider 内）→ 查单 → 归属/渠道一致性 → 金额 fail-closed
  → 已 paid 快速 ACK → mark_paid_and_grant（恰好一次）→ ok ACK
金额/币种不符与 closed 吸态返回 422 并记 error_events，零状态变更；
验签失败返回渠道约定的失败 ACK（渠道按此决定重发）。
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from backend.app.api.dependencies import (
    get_error_event_repository,
    get_payment_order_repository,
    get_payment_providers,
    get_user_account_repository,
)
from backend.app.api.feature_gates import require_payments_enabled
from backend.app.core.auth import RequireUser, extract_user_id
from backend.app.core.client_ip import client_ip_from_request
from backend.app.models.schema_payments import (
    PAYMENT_CHANNELS,
    CreatePaymentOrderRequest,
    CreatePaymentOrderResponse,
    PaymentChannelPublic,
    PaymentInstructionPublic,
    PaymentOrderListResponse,
    PaymentOrderPublic,
    PaymentPlanPublic,
    PaymentPlansResponse,
)
from backend.app.repositories.error_event_repository import (
    ErrorEventInsert,
    ErrorEventRepository,
)
from backend.app.repositories.payment_order_repository import PaymentOrderRepository
from backend.app.repositories.user_account_repository import UserAccountRepository
from backend.app.services.auth.rate_limit import RateLimitExceededError, hit_rate_limit
from backend.app.services.payments.grant import mark_paid_and_grant
from backend.app.services.payments.orders import (
    ORDER_STATUS_CLOSED,
    ORDER_STATUS_PAID,
    normalize_order_status,
)
from backend.app.services.payments.plans import MEMBERSHIP_PLANS, UnknownPlanError, get_plan
from backend.app.services.payments.providers.base import (
    CallbackVerificationError,
    PaymentProvider,
    ProviderNotConfiguredError,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_payments_enabled)])

# IP 级固定窗口限速：plans 浏览 60/min，下单按用户 10/min，回调按 IP 120/min
# （渠道重发通知合法频率低但需留余量；Redis 故障 fail-open，可用性优先）。
_RATE_LIMIT_WINDOW_SECONDS = 60
_PLANS_RATE_LIMIT = 60
_CREATE_ORDER_RATE_LIMIT = 10
_CALLBACK_RATE_LIMIT = 120


async def _enforce_rate_limit(
    request: Request,
    *,
    action: str,
    identity: str,
    limit: int,
) -> None:
    """固定窗口限速；Redis 不可用时放行并告警（routes_push 先例）。"""
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return
    try:
        await hit_rate_limit(
            redis_client,
            action=action,
            identity=identity,
            limit=limit,
            window_seconds=_RATE_LIMIT_WINDOW_SECONDS,
        )
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate_limited",
        ) from exc
    except Exception:
        logger.warning("[Payments] rate limit check failed, allowing request", exc_info=True)


def _to_public_order(row: Mapping[str, Any]) -> PaymentOrderPublic:
    """行 → 用户侧视图；永不含 callback_payload/idempotency_key 内部列。"""
    return PaymentOrderPublic(
        order_no=str(row["order_no"]),
        plan_code=str(row["plan_code"]),
        channel=str(row["channel"]),
        amount_cents=int(row["amount_cents"]),
        currency=str(row["currency"]),
        status=normalize_order_status(row.get("status")),
        channel_order_no=str(row.get("channel_order_no") or ""),
        expires_at=row["expires_at"],
        paid_at=row.get("paid_at"),
        created_at=row["created_at"],
    )


def _public_base_url(request: Request) -> str:
    """回调/回跳公网基址：显式配置优先，缺省按请求 Host 推导。"""
    from backend.app.core.config import settings

    configured = settings.payments_public_base_url.strip().rstrip("/")
    if configured:
        return configured
    return str(request.base_url).rstrip("/")


def _generate_order_no() -> str:
    """业务单号：P + UTC 时间戳 + 6 位随机十六进制（冲突由仓储唯一索引兜底）。"""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"P{stamp}{secrets.token_hex(3).upper()}"


@router.get("/payments/plans", response_model=PaymentPlansResponse)
async def list_payment_plans(
    request: Request,
    providers: dict[str, PaymentProvider] = Depends(get_payment_providers),
) -> PaymentPlansResponse:
    """套餐与渠道可用性；匿名可读（收银台首屏），IP 60/min。"""
    await _enforce_rate_limit(
        request,
        action="payments.plans",
        identity=client_ip_from_request(request),
        limit=_PLANS_RATE_LIMIT,
    )
    return PaymentPlansResponse(
        plans=[
            PaymentPlanPublic(
                code=plan.code,
                tier=plan.tier,
                amount_cents=plan.amount_cents,
                currency=plan.currency,
                months=plan.months,
            )
            for plan in MEMBERSHIP_PLANS.values()
        ],
        channels=[
            PaymentChannelPublic(channel=channel, available=provider.is_configured())
            for channel, provider in sorted(providers.items())
        ],
    )


@router.post("/payments/orders", response_model=CreatePaymentOrderResponse)
async def create_payment_order(
    payload: CreatePaymentOrderRequest,
    request: Request,
    user: dict[str, Any] = Depends(RequireUser),
    orders: PaymentOrderRepository = Depends(get_payment_order_repository),
    providers: dict[str, PaymentProvider] = Depends(get_payment_providers),
) -> CreatePaymentOrderResponse:
    """创建待支付订单并返回渠道支付指令；幂等键命中返回既有单。"""
    from backend.app.core.config import settings

    user_id = extract_user_id(user)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户身份无效",
        )
    await _enforce_rate_limit(
        request,
        action="payments.create_order",
        identity=f"user:{user_id}",
        limit=_CREATE_ORDER_RATE_LIMIT,
    )

    try:
        plan = get_plan(payload.plan_code)
    except UnknownPlanError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unknown_plan",
        ) from exc
    if payload.channel not in PAYMENT_CHANNELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unknown_channel",
        )
    provider = providers[payload.channel]
    if not provider.is_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="payment_channel_not_configured",
        )

    base_url = _public_base_url(request)
    notify_url = f"{base_url}/api/payments/callback/{payload.channel}"
    return_url = f"{base_url}/membership/checkout"

    # 幂等键命中：返回既有单并重新取支付指令（渠道侧按 order_no 幂等）。
    idempotency_key = payload.idempotency_key.strip()
    if idempotency_key:
        existing = await asyncio.to_thread(
            orders.get_order_by_user_and_idempotency_key,
            user_id=user_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            instruction = await asyncio.to_thread(
                provider.create_payment,
                order=existing,
                notify_url=notify_url,
                return_url=return_url,
            )
            return CreatePaymentOrderResponse(
                order=_to_public_order(existing),
                instruction=PaymentInstructionPublic(
                    kind=instruction.kind, content=instruction.content
                ),
            )

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=int(settings.payments_order_ttl_minutes))
    order_row: dict[str, Any] | None = None
    # order_no 冲突（概率极低）换号重试；幂等键并发冲突按既有单回读。
    for _ in range(3):
        order_row = await asyncio.to_thread(
            orders.create_order,
            order_no=_generate_order_no(),
            user_id=user_id,
            plan_code=plan.code,
            channel=payload.channel,
            amount_cents=plan.amount_cents,
            currency=plan.currency,
            idempotency_key=idempotency_key,
            expires_at=expires_at,
        )
        if order_row is not None:
            break
        if idempotency_key:
            order_row = await asyncio.to_thread(
                orders.get_order_by_user_and_idempotency_key,
                user_id=user_id,
                idempotency_key=idempotency_key,
            )
            if order_row is not None:
                break
    if order_row is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="order_create_conflict",
        )

    try:
        instruction = await asyncio.to_thread(
            provider.create_payment,
            order=order_row,
            notify_url=notify_url,
            return_url=return_url,
        )
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="payment_channel_not_configured",
        ) from exc

    return CreatePaymentOrderResponse(
        order=_to_public_order(order_row),
        instruction=PaymentInstructionPublic(
            kind=instruction.kind, content=instruction.content
        ),
    )


@router.get("/payments/orders", response_model=PaymentOrderListResponse)
async def list_my_payment_orders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=50),
    user: dict[str, Any] = Depends(RequireUser),
    orders: PaymentOrderRepository = Depends(get_payment_order_repository),
) -> PaymentOrderListResponse:
    """我的订单（id DESC 新到旧）。"""
    user_id = extract_user_id(user)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户身份无效",
        )
    rows, total = await asyncio.to_thread(
        orders.list_user_orders, user_id=user_id, page=page, page_size=page_size
    )
    return PaymentOrderListResponse(
        items=[_to_public_order(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/payments/orders/{order_no}", response_model=PaymentOrderPublic)
async def get_my_payment_order(
    order_no: str,
    user: dict[str, Any] = Depends(RequireUser),
    orders: PaymentOrderRepository = Depends(get_payment_order_repository),
) -> PaymentOrderPublic:
    """单订单详情；非属主与不存在同形 404（不泄露单号存在性）。"""
    user_id = extract_user_id(user)
    row = await asyncio.to_thread(orders.get_order_by_order_no, order_no)
    if row is None or user_id is None or int(row["user_id"]) != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="order_not_found",
        )
    return _to_public_order(row)


@router.post("/payments/callback/{channel}")
async def payment_callback(
    channel: str,
    request: Request,
    orders: PaymentOrderRepository = Depends(get_payment_order_repository),
    users: UserAccountRepository = Depends(get_user_account_repository),
    providers: dict[str, PaymentProvider] = Depends(get_payment_providers),
    error_events: ErrorEventRepository = Depends(get_error_event_repository),
) -> Response:
    """渠道异步通知入口：验签 → 一致性/金额校验 → 恰好一次发权益 → ACK。"""
    provider = providers.get(channel)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="unknown_channel",
        )
    await _enforce_rate_limit(
        request,
        action="payments.callback",
        identity=client_ip_from_request(request),
        limit=_CALLBACK_RATE_LIMIT,
    )

    raw_body = await request.body()
    try:
        verified = await asyncio.to_thread(
            provider.verify_and_parse_callback,
            raw_body=raw_body,
            headers=dict(request.headers),
        )
    except CallbackVerificationError:
        logger.warning("[Payments] callback verification failed: channel=%s", channel)
        return provider.build_ack_response(ok=False)
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="payment_channel_not_configured",
        ) from exc

    order = await asyncio.to_thread(orders.get_order_by_order_no, verified.order_no)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="order_not_found",
        )

    # 归属一致性：单号所属渠道须与回调入口一致；已绑定渠道单号不得漂移。
    if order["channel"] != channel:
        raise HTTPException(
            status_code=422,  # 项目惯例：422 数字字面量
            detail="order_channel_mismatch",
        )
    bound_channel_order_no = str(order.get("channel_order_no") or "")
    if bound_channel_order_no and bound_channel_order_no != verified.channel_order_no:
        raise HTTPException(
            status_code=422,  # 项目惯例：422 数字字面量
            detail="channel_order_no_mismatch",
        )

    # 金额/币种 fail-closed：不符即记 error_events + 422，零状态变更。
    if (
        int(verified.amount_cents) != int(order["amount_cents"])
        or verified.currency != order["currency"]
    ):
        await asyncio.to_thread(
            error_events.insert_events,
            [
                ErrorEventInsert(
                    level="ERROR",
                    logger_name="payments.callback",
                    message=(
                        "payment amount mismatch: "
                        f"order_no={order['order_no']} channel={channel} "
                        f"expected={order['amount_cents']}{order['currency']} "
                        f"got={verified.amount_cents}{verified.currency}"
                    ),
                    exception_type="PaymentAmountMismatch",
                )
            ],
        )
        raise HTTPException(
            status_code=422,  # 项目惯例：422 数字字面量
            detail="amount_mismatch",
        )

    order_status = normalize_order_status(order.get("status"))
    if order_status == ORDER_STATUS_PAID:
        # 渠道重发：已发放，直接快速 ACK
        return provider.build_ack_response(ok=True)
    if order_status == ORDER_STATUS_CLOSED:
        # 吸态：人工关单后渠道仍报支付成功 → 人工介入退款，绝不自动发放
        await asyncio.to_thread(
            error_events.insert_events,
            [
                ErrorEventInsert(
                    level="ERROR",
                    logger_name="payments.callback",
                    message=(
                        "payment callback on closed order: "
                        f"order_no={order['order_no']} channel={channel}"
                    ),
                    exception_type="PaymentOnClosedOrder",
                )
            ],
        )
        raise HTTPException(
            status_code=422,  # 项目惯例：422 数字字面量
            detail="order_closed",
        )

    # pending 正常发放；expired 迟到支付特许放行（钱已收必须发权益）
    plan = get_plan(order["plan_code"])
    result = await asyncio.to_thread(
        mark_paid_and_grant,
        orders=orders,
        users=users,
        order=order,
        verified=verified,
        plan=plan,
        now=datetime.now(timezone.utc),
        callback_payload=raw_body.decode("utf-8", errors="replace"),
    )
    if not result.granted and result.note == "user_missing":
        logger.error(
            "[Payments] grant skipped, user missing: order_no=%s", order["order_no"]
        )
    return provider.build_ack_response(ok=True)
