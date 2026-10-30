"""闪光工坊（ShinyDesk）激活码收单路由：游客 PayPal 下单 → 发码。

公开接口（payments 总开关 + SHINYDESK_CHECKOUT_ENABLED 双门控，关闭即 404）：
  GET  /api/shinydesk/checkout                     可购买状态与价格
  POST /api/shinydesk/orders                       建单 → PayPal approve 链接 + 浏览器凭据
  POST /api/shinydesk/orders/{order_no}/confirm    PayPal 回跳后服务端 capture 并发码
  POST /api/shinydesk/orders/{order_no}/status     凭据查单（paid 未发码时顺带重试发码）
  POST /api/shinydesk/lookup                       单号或 PayPal 交易号 + 付款邮箱找回码
webhook 不另开入口：/api/payments/callback/overseas_redirect 验签后调用
dispatch_paypal_event，按 SD 单号 / capture id 认领本商品事件，其余落回会员逻辑。
管理员接口（RequireAdmin）：/api/ops/shinydesk/orders[...]，作废/重试/补发邮件。
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from backend.app.api.dependencies import (
    get_error_event_repository,
    get_payment_providers,
    get_postgres_database,
)
from backend.app.api.feature_gates import require_payments_enabled
from backend.app.api.routes_payments import _enforce_rate_limit, _public_base_url
from backend.app.core.auth import RequireAdmin
from backend.app.core.client_ip import client_ip_from_request
from backend.app.repositories.error_event_repository import ErrorEventRepository
from backend.app.repositories.postgres_shinydesk_order_repository import PostgresShinyDeskOrderRepository
from backend.app.repositories.shinydesk_order_repository import ShinyDeskOrderRepository
from backend.app.services.email_service import build_email_service
from backend.app.services.payments.providers.base import (
    CallbackVerificationError,
    ChannelUpstreamError,
    PaymentProvider,
    ProviderNotConfiguredError,
)
from backend.app.services.payments.providers.overseas_redirect import CHANNEL_OVERSEAS_REDIRECT
from backend.app.services.payments.providers.paypal import PayPalOrderNotCapturable, PayPalProvider
from backend.app.services.payments.runtime_config import resolve_payment_config
from backend.app.services.shinydesk import checkout
from backend.app.services.shinydesk.license_client import (
    LicenseServiceError,
    ShinyDeskLicenseClient,
    build_license_client,
)
from backend.app.services.shinydesk.notify import SendPlain, send_license_email
from backend.app.services.shinydesk.product import (
    AMOUNT_CENTS,
    CURRENCY,
    PRODUCT_CODE,
    ShinyDeskConfig,
    checkout_order_mapping,
    generate_order_no,
    is_shinydesk_order_no,
    load_config,
)

logger = logging.getLogger(__name__)

_CREATE_LIMIT = 6
_CONFIRM_LIMIT = 30
_LOOKUP_LIMIT = 10
_LOOKUP_FAILURE_LOCK = 10
_ORDER_DISPLAY_TTL = timedelta(hours=3)  # PayPal approve 链接约 3 小时有效，仅作展示
_PUBLIC_STATUS = {"pending": "pending", "paid": "processing", "fulfilled": "fulfilled", "revoked": "revoked", "closed": "closed"}


# ── 依赖 ─────────────────────────────────────────────────────────────────


def get_shinydesk_config() -> ShinyDeskConfig:
    return load_config()


def require_shinydesk_enabled(config: ShinyDeskConfig = Depends(get_shinydesk_config)) -> None:
    if not config.enabled:
        raise HTTPException(status_code=404, detail="Not Found")


def get_shinydesk_orders(request: Request) -> ShinyDeskOrderRepository:
    repository = getattr(request.app.state, "shinydesk_orders", None)
    if repository is None:
        repository = PostgresShinyDeskOrderRepository(get_postgres_database(request))
        request.app.state.shinydesk_orders = repository
    return repository


def get_shinydesk_license_client(
    config: ShinyDeskConfig = Depends(get_shinydesk_config),
) -> ShinyDeskLicenseClient | None:
    return build_license_client(config)


def get_shinydesk_mailer(request: Request) -> SendPlain | None:
    try:
        service = build_email_service(getattr(request.app.state, "redis", None))
    except Exception:
        logger.warning("[ShinyDesk] email service unavailable", exc_info=True)
        return None
    return service.send_plain_message if service.delivery_configured else None


router = APIRouter(dependencies=[Depends(require_payments_enabled), Depends(require_shinydesk_enabled)])
ops_router = APIRouter()


# ── 视图 ─────────────────────────────────────────────────────────────────


def _mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    if not domain:
        return ""
    return f"{name[:1]}***@{domain}"


def _public_order(row: Mapping[str, Any]) -> dict[str, Any]:
    fulfilled = row["status"] == "fulfilled"
    return {
        "order_no": row["order_no"],
        "status": _PUBLIC_STATUS.get(str(row["status"]), "closed"),
        "amount_cents": int(row["amount_cents"]),
        "currency": row["currency"],
        "license_code": row["license_code"] if fulfilled else None,
        "terms": {"permanent": True, "desktop_devices": 1, "android_devices": 1, "concurrent_jobs": 2},
        "payer_email": _mask_email(str(row.get("payer_email") or "")),
        "email_status": row.get("email_status") or "none",
        "paypal_transaction_id": row.get("paypal_capture_id") if fulfilled else None,
        "paid_at": row.get("paid_at"),
    }


def _ops_order(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in ("access_token_hash", "callback_payload")}


def _paypal_provider(providers: Mapping[str, PaymentProvider]) -> PayPalProvider | None:
    provider = providers.get(CHANNEL_OVERSEAS_REDIRECT)
    if isinstance(provider, PayPalProvider) and provider.is_configured():
        return provider
    return None


def _return_url(config: ShinyDeskConfig) -> str:
    separator = "&" if "?" in config.site_url else "?"
    return f"{config.site_url}{separator}lang=en"


async def _after_fulfilled(
    row: Mapping[str, Any], *, orders: ShinyDeskOrderRepository, config: ShinyDeskConfig, mailer: SendPlain | None
) -> dict[str, Any]:
    if row["status"] != "fulfilled":
        return dict(row)
    await send_license_email(orders=orders, order=row, site_url=config.site_url, send_plain=mailer)
    return await asyncio.to_thread(orders.get_by_order_no, str(row["order_no"])) or dict(row)


async def _fulfill(
    *,
    orders: ShinyDeskOrderRepository,
    license_client: ShinyDeskLicenseClient | None,
    error_events: ErrorEventRepository,
    row: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            checkout.fulfill_from_paypal_order,
            orders=orders,
            license_client=license_client,
            error_events=error_events,
            order=row,
            order_payload=payload,
            now=datetime.now(timezone.utc),
        )
    except checkout.ShinyDeskMismatch as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc  # 项目惯例：422 数字字面量


# ── 公开接口 ─────────────────────────────────────────────────────────────


class AccessRequest(BaseModel):
    access_token: str = Field(min_length=1, max_length=200)


class ConfirmRequest(AccessRequest):
    paypal_order_id: str = Field(default="", max_length=40)


class LookupRequest(BaseModel):
    reference: str = Field(min_length=1, max_length=60)
    email: str = Field(min_length=3, max_length=320)


@router.get("/shinydesk/checkout")
async def checkout_status(
    config: ShinyDeskConfig = Depends(get_shinydesk_config),
    providers: dict[str, PaymentProvider] = Depends(get_payment_providers),
    license_client: ShinyDeskLicenseClient | None = Depends(get_shinydesk_license_client),
) -> dict[str, Any]:
    return {
        "available": _paypal_provider(providers) is not None and license_client is not None,
        "product": PRODUCT_CODE,
        "amount_cents": AMOUNT_CENTS,
        "currency": CURRENCY,
        "terms": {"permanent": True, "desktop_devices": 1, "android_devices": 1, "concurrent_jobs": 2},
    }


@router.post("/shinydesk/orders")
async def create_order(
    request: Request,
    config: ShinyDeskConfig = Depends(get_shinydesk_config),
    orders: ShinyDeskOrderRepository = Depends(get_shinydesk_orders),
    providers: dict[str, PaymentProvider] = Depends(get_payment_providers),
    license_client: ShinyDeskLicenseClient | None = Depends(get_shinydesk_license_client),
) -> dict[str, Any]:
    provider = _paypal_provider(providers)
    if provider is None or license_client is None:
        raise HTTPException(status_code=503, detail="checkout_unavailable")
    client_ip = client_ip_from_request(request)
    await _enforce_rate_limit(request, action="shinydesk.create_order", identity=client_ip, limit=_CREATE_LIMIT)
    token, token_hash = checkout.new_access_token()
    expires_at = datetime.now(timezone.utc) + _ORDER_DISPLAY_TTL
    row: dict[str, Any] | None = None
    for _ in range(3):
        row = await asyncio.to_thread(
            orders.create_order,
            order_no=generate_order_no(),
            product_code=PRODUCT_CODE,
            amount_cents=AMOUNT_CENTS,
            currency=CURRENCY,
            access_token_hash=token_hash,
            client_ip=client_ip,
            expires_at=expires_at,
        )
        if row is not None:
            break
    if row is None:
        raise HTTPException(status_code=500, detail="order_create_conflict")
    notify_url = f"{_public_base_url(request, resolve_payment_config())}/api/payments/callback/{CHANNEL_OVERSEAS_REDIRECT}"
    try:
        instruction = await asyncio.to_thread(
            provider.create_payment, order=checkout_order_mapping(row), notify_url=notify_url, return_url=_return_url(config)
        )
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail="checkout_unavailable") from exc
    except ChannelUpstreamError as exc:
        raise HTTPException(status_code=502, detail="payment_channel_upstream_error") from exc
    # approve 链接的 token 参数就是 PayPal 订单号：建单即绑定，回跳与 webhook 都按它核对。
    paypal_order_id = (parse_qs(urlparse(instruction.content).query).get("token") or [""])[0]
    if checkout.is_paypal_id(paypal_order_id):
        await asyncio.to_thread(orders.bind_paypal_order, order_id=int(row["id"]), paypal_order_id=paypal_order_id)
    return {
        "order_no": row["order_no"],
        "access_token": token,
        "approve_url": instruction.content,
        "amount_cents": AMOUNT_CENTS,
        "currency": CURRENCY,
    }


async def _authorized_order(orders: ShinyDeskOrderRepository, order_no: str, token: str) -> dict[str, Any]:
    row = await asyncio.to_thread(orders.get_by_order_no, order_no) if is_shinydesk_order_no(order_no) else None
    if row is None or not checkout.token_matches(row, token):
        raise HTTPException(status_code=404, detail="order_not_found")
    return row


@router.post("/shinydesk/orders/{order_no}/confirm")
async def confirm_order(
    order_no: str,
    payload: ConfirmRequest,
    request: Request,
    config: ShinyDeskConfig = Depends(get_shinydesk_config),
    orders: ShinyDeskOrderRepository = Depends(get_shinydesk_orders),
    providers: dict[str, PaymentProvider] = Depends(get_payment_providers),
    license_client: ShinyDeskLicenseClient | None = Depends(get_shinydesk_license_client),
    error_events: ErrorEventRepository = Depends(get_error_event_repository),
    mailer: SendPlain | None = Depends(get_shinydesk_mailer),
) -> dict[str, Any]:
    await _enforce_rate_limit(request, action="shinydesk.confirm", identity=client_ip_from_request(request), limit=_CONFIRM_LIMIT)
    row = await _authorized_order(orders, order_no, payload.access_token)
    if row["status"] == "pending":
        provider = _paypal_provider(providers)
        if provider is None:
            raise HTTPException(status_code=503, detail="checkout_unavailable")
        paypal_order_id = row.get("paypal_order_id") or ""
        requested = payload.paypal_order_id.strip()
        if requested and paypal_order_id and requested != paypal_order_id:
            raise HTTPException(status_code=422, detail="paypal_order_mismatch")
        if not paypal_order_id:
            if not checkout.is_paypal_id(requested):
                raise HTTPException(status_code=422, detail="paypal_order_missing")
            if await asyncio.to_thread(orders.bind_paypal_order, order_id=int(row["id"]), paypal_order_id=requested) is None:
                raise HTTPException(status_code=422, detail="paypal_order_mismatch")
            paypal_order_id = requested
            row = await asyncio.to_thread(orders.get_by_order_no, order_no) or row
        try:
            paypal_order = await asyncio.to_thread(
                provider.capture_order_details, paypal_order_id=paypal_order_id, request_id=order_no
            )
        except PayPalOrderNotCapturable as exc:
            return {**_public_order(row), "payment_state": exc.issue}
        except ChannelUpstreamError as exc:
            raise HTTPException(status_code=502, detail="payment_channel_upstream_error") from exc
        try:
            row = await _fulfill(orders=orders, license_client=license_client, error_events=error_events, row=row, payload=paypal_order)
        except CallbackVerificationError as exc:
            raise HTTPException(status_code=502, detail="payment_channel_invalid_response") from exc
    elif row["status"] == "paid":
        row = await asyncio.to_thread(
            checkout.issue_license, orders=orders, license_client=license_client, error_events=error_events, order=row
        )
    row = await _after_fulfilled(row, orders=orders, config=config, mailer=mailer)
    return _public_order(row)


@router.post("/shinydesk/orders/{order_no}/status")
async def order_status(
    order_no: str,
    payload: AccessRequest,
    request: Request,
    config: ShinyDeskConfig = Depends(get_shinydesk_config),
    orders: ShinyDeskOrderRepository = Depends(get_shinydesk_orders),
    license_client: ShinyDeskLicenseClient | None = Depends(get_shinydesk_license_client),
    error_events: ErrorEventRepository = Depends(get_error_event_repository),
    mailer: SendPlain | None = Depends(get_shinydesk_mailer),
) -> dict[str, Any]:
    await _enforce_rate_limit(request, action="shinydesk.confirm", identity=client_ip_from_request(request), limit=_CONFIRM_LIMIT)
    row = await _authorized_order(orders, order_no, payload.access_token)
    if row["status"] == "paid":
        row = await asyncio.to_thread(
            checkout.issue_license, orders=orders, license_client=license_client, error_events=error_events, order=row
        )
    row = await _after_fulfilled(row, orders=orders, config=config, mailer=mailer)
    return _public_order(row)


@router.post("/shinydesk/lookup")
async def lookup_order(
    payload: LookupRequest,
    request: Request,
    orders: ShinyDeskOrderRepository = Depends(get_shinydesk_orders),
    license_client: ShinyDeskLicenseClient | None = Depends(get_shinydesk_license_client),
    error_events: ErrorEventRepository = Depends(get_error_event_repository),
) -> dict[str, Any]:
    await _enforce_rate_limit(request, action="shinydesk.lookup", identity=client_ip_from_request(request), limit=_LOOKUP_LIMIT)
    reference = payload.reference.strip().upper()
    row = None
    if is_shinydesk_order_no(reference):
        row = await asyncio.to_thread(orders.get_by_order_no, reference)
    elif checkout.is_paypal_id(reference):
        row = await asyncio.to_thread(orders.get_by_capture_id, reference) or await asyncio.to_thread(
            orders.get_by_paypal_order_id, reference
        )
    not_found = HTTPException(status_code=404, detail="order_not_found")
    if row is None or int(row.get("lookup_failures") or 0) >= _LOOKUP_FAILURE_LOCK:
        raise not_found
    stored = str(row.get("payer_email") or "").strip().casefold()
    given = payload.email.strip().casefold()
    if not stored or not secrets.compare_digest(stored.encode("utf-8"), given.encode("utf-8")):
        await asyncio.to_thread(orders.record_lookup_failure, order_id=int(row["id"]))
        raise not_found
    if row["status"] == "paid":
        row = await asyncio.to_thread(
            checkout.issue_license, orders=orders, license_client=license_client, error_events=error_events, order=row
        )
    return _public_order(row)


# ── webhook 分流（routes_payments.payment_callback 调用）────────────────


async def dispatch_paypal_event(
    request: Request,
    provider: PayPalProvider,
    event: Mapping[str, Any],
    error_events: ErrorEventRepository,
) -> Response | None:
    """认领本商品的已验签 PayPal 事件并返回 ACK；不是本商品的返回 None。"""
    config = load_config()
    if not config.enabled:
        return None
    event_type = str(event.get("event_type") or "")
    resource = event.get("resource")
    if not isinstance(resource, Mapping):
        return None
    orders = get_shinydesk_orders(request)
    ack = provider.build_ack_response(ok=True)

    if event_type in ("CHECKOUT.ORDER.APPROVED", "PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.PENDING", "PAYMENT.CAPTURE.DENIED"):
        order_no = checkout.event_order_no(event)
        if not is_shinydesk_order_no(order_no):
            return None
        row = await asyncio.to_thread(orders.get_by_order_no, order_no)
        if row is None:
            raise HTTPException(status_code=404, detail="order_not_found")
        if event_type == "CHECKOUT.ORDER.APPROVED":
            try:
                paypal_order = await asyncio.to_thread(
                    provider.capture_order_details, paypal_order_id=str(resource.get("id") or ""), request_id=order_no
                )
            except PayPalOrderNotCapturable:
                return ack
        elif event_type == "PAYMENT.CAPTURE.COMPLETED":
            related = resource.get("supplementary_data")
            related = related.get("related_ids") if isinstance(related, Mapping) else None
            paypal_order_id = related.get("order_id") if isinstance(related, Mapping) else None
            if not checkout.is_paypal_id(paypal_order_id):
                paypal_order_id = row.get("paypal_order_id")
            if not checkout.is_paypal_id(paypal_order_id):
                raise CallbackVerificationError("paypal capture missing order id")
            paypal_order = await asyncio.to_thread(provider.get_order_details, paypal_order_id=paypal_order_id)
        else:
            return ack  # PENDING / DENIED：不落账，等 COMPLETED
        license_client = build_license_client(config)
        row = await _fulfill(orders=orders, license_client=license_client, error_events=error_events, row=row, payload=paypal_order)
        await _after_fulfilled(row, orders=orders, config=config, mailer=get_shinydesk_mailer(request))
        return ack

    if event_type in ("PAYMENT.CAPTURE.REFUNDED", "PAYMENT.CAPTURE.REVERSED"):
        capture_id = checkout.refunded_capture_id(resource)
        row = await asyncio.to_thread(orders.get_by_capture_id, capture_id) if capture_id else None
        if row is None:
            return None
        reason = "refund" if event_type.endswith("REFUNDED") else "reversal"
        try:
            await asyncio.to_thread(
                checkout.revoke_order,
                orders=orders,
                license_client=build_license_client(config),
                error_events=error_events,
                order=row,
                reason=reason,
            )
        except LicenseServiceError as exc:
            # 授权服务器暂不可达：5xx 让 PayPal 重发，码作废不能静默丢失。
            raise HTTPException(status_code=503, detail="license_service_unavailable") from exc
        return ack

    if event_type.startswith("CUSTOMER.DISPUTE."):
        rows = []
        for capture_id in checkout.disputed_capture_ids(resource):
            found = await asyncio.to_thread(orders.get_by_capture_id, capture_id)
            if found is not None:
                rows.append(found)
        if not rows:
            return None
        state = str(resource.get("status") or event_type.rsplit(".", 1)[-1])
        outcome = resource.get("dispute_outcome")
        if isinstance(outcome, Mapping) and outcome.get("outcome_code"):
            state = f"{state}:{outcome['outcome_code']}"
        for row in rows:
            await asyncio.to_thread(orders.set_dispute_status, order_id=int(row["id"]), dispute_status=state)
            checkout._alert(
                error_events,
                f"shinydesk dispute {event_type}: order_no={row['order_no']} state={state} (decide manually: ops revoke)",
                "ShinyDeskDispute",
                "WARNING",
            )
        return ack
    return None


# ── 管理员 ───────────────────────────────────────────────────────────────


class RevokeRequest(BaseModel):
    reason: str = Field(pattern="^(manual|dispute|refund|reversal)$")


async def _ops_row(orders: ShinyDeskOrderRepository, order_no: str) -> dict[str, Any]:
    row = await asyncio.to_thread(orders.get_by_order_no, order_no)
    if row is None:
        raise HTTPException(status_code=404, detail="order_not_found")
    return row


@ops_router.get("/ops/shinydesk/orders")
async def ops_list_orders(
    q: str = Query(default="", max_length=320),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _: dict = Depends(RequireAdmin),
    orders: ShinyDeskOrderRepository = Depends(get_shinydesk_orders),
) -> dict[str, Any]:
    rows, total = await asyncio.to_thread(orders.list_orders, query=q, page=page, page_size=page_size)
    return {"items": [_ops_order(row) for row in rows], "total": total, "page": page, "page_size": page_size}


@ops_router.post("/ops/shinydesk/orders/{order_no}/revoke")
async def ops_revoke_order(
    order_no: str,
    payload: RevokeRequest,
    _: dict = Depends(RequireAdmin),
    orders: ShinyDeskOrderRepository = Depends(get_shinydesk_orders),
    license_client: ShinyDeskLicenseClient | None = Depends(get_shinydesk_license_client),
    error_events: ErrorEventRepository = Depends(get_error_event_repository),
) -> dict[str, Any]:
    row = await _ops_row(orders, order_no)
    if row["status"] not in ("paid", "fulfilled", "revoked"):
        raise HTTPException(status_code=409, detail="order_not_paid")
    try:
        row = await asyncio.to_thread(
            checkout.revoke_order, orders=orders, license_client=license_client, error_events=error_events, order=row, reason=payload.reason
        )
    except LicenseServiceError as exc:
        raise HTTPException(status_code=502, detail="license_service_unavailable") from exc
    return _ops_order(row)


@ops_router.post("/ops/shinydesk/orders/{order_no}/retry")
async def ops_retry_order(
    order_no: str,
    request: Request,
    _: dict = Depends(RequireAdmin),
    config: ShinyDeskConfig = Depends(get_shinydesk_config),
    orders: ShinyDeskOrderRepository = Depends(get_shinydesk_orders),
    providers: dict[str, PaymentProvider] = Depends(get_payment_providers),
    license_client: ShinyDeskLicenseClient | None = Depends(get_shinydesk_license_client),
    error_events: ErrorEventRepository = Depends(get_error_event_repository),
) -> dict[str, Any]:
    """pending 且已绑定 PayPal 单号 → 查 PayPal 订单落账；paid → 重新发码。"""
    row = await _ops_row(orders, order_no)
    if row["status"] == "pending" and row.get("paypal_order_id"):
        provider = _paypal_provider(providers)
        if provider is None:
            raise HTTPException(status_code=503, detail="checkout_unavailable")
        try:
            paypal_order = await asyncio.to_thread(provider.get_order_details, paypal_order_id=str(row["paypal_order_id"]))
        except ChannelUpstreamError as exc:
            raise HTTPException(status_code=502, detail="payment_channel_upstream_error") from exc
        row = await _fulfill(orders=orders, license_client=license_client, error_events=error_events, row=row, payload=paypal_order)
    elif row["status"] == "paid":
        row = await asyncio.to_thread(
            checkout.issue_license, orders=orders, license_client=license_client, error_events=error_events, order=row
        )
    row = await _after_fulfilled(row, orders=orders, config=config, mailer=get_shinydesk_mailer(request))
    return _ops_order(row)


@ops_router.post("/ops/shinydesk/orders/{order_no}/resend-email")
async def ops_resend_email(
    order_no: str,
    request: Request,
    _: dict = Depends(RequireAdmin),
    config: ShinyDeskConfig = Depends(get_shinydesk_config),
    orders: ShinyDeskOrderRepository = Depends(get_shinydesk_orders),
) -> dict[str, Any]:
    row = await _ops_row(orders, order_no)
    if row["status"] != "fulfilled":
        raise HTTPException(status_code=409, detail="order_not_fulfilled")
    await asyncio.to_thread(orders.reset_email, order_id=int(row["id"]))
    row = await _after_fulfilled(row, orders=orders, config=config, mailer=get_shinydesk_mailer(request))
    return _ops_order(row)
