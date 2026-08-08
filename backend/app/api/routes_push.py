from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from backend.app.api.dependencies import (
    get_push_channel_service,
    get_user_subscription_service,
)
from backend.app.core.auth import RequireUser
from backend.app.core.client_ip import client_ip_from_request
from backend.app.models.schema_push import (
    CreatePushChannelRequest,
    CreateSubscriptionRequest,
    PushChannelResponse,
    SubscriptionResponse,
    UpdatePushChannelRequest,
    UpdateSubscriptionRequest,
    VerifyPushChannelRequest,
)
from backend.app.services.auth.rate_limit import RateLimitExceededError, hit_rate_limit
from backend.app.services.email_service import (
    BriefingDeliveryError,
    EmailService,
    OtpDeliveryUnavailableError,
    OtpSendRateLimitedError,
    build_email_service,
)
from backend.app.services.push.channel_service import PushChannelService
from backend.app.services.push.errors import (
    InvalidChannelOtpError,
    PushChannelDisabledError,
    PushChannelDuplicateError,
    PushChannelNotFoundError,
    PushChannelNotVerifiedError,
    PushDomainError,
    SubscriptionDuplicateError,
    SubscriptionNotFoundError,
    WebhookDeliveryError,
    WebhookProbeFailedError,
    WebhookUrlError,
)
from backend.app.services.push.secrets import (
    PushChannelSecretError,
    build_push_channel_secret_box,
)
from backend.app.services.push.subscription_service import UserSubscriptionService
from backend.app.services.push.webhook_service import WebhookSender

logger = logging.getLogger(__name__)

router = APIRouter()

# 推送端点 IP 级固定窗口限速（防 OTP 滥用与测试/探测投递轰炸）
_PUSH_RATE_LIMIT_WINDOW_SECONDS = 600
_CHANNEL_OTP_SEND_RATE_LIMIT = 5
_CHANNEL_TEST_RATE_LIMIT = 5
_CHANNEL_WEBHOOK_CREATE_RATE_LIMIT = 5


async def _enforce_rate_limit(request: Request, *, action: str, limit: int) -> None:
    """执行 IP 级限速；Redis 不可用时放行并告警（可用性优先于限速严格性）。

    客户端 IP 统一走 core.client_ip 的可信代理解析：不可信对端不采信
    X-Forwarded-For，防止伪造 XFF 拆分限速桶。
    """
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return
    try:
        await hit_rate_limit(
            redis_client,
            action=action,
            identity=client_ip_from_request(request),
            limit=limit,
            window_seconds=_PUSH_RATE_LIMIT_WINDOW_SECONDS,
        )
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后再试",
        ) from exc
    except Exception:
        logger.warning(
            "[Push] rate limit check failed, allowing request", exc_info=True
        )


def _get_email_service(request: Request) -> EmailService:
    """从 app.state 获取 Redis 并构造 EmailService 实例。"""
    redis_client = getattr(request.app.state, "redis", None)
    return build_email_service(redis_client)


def _user_id(user: dict[str, Any]) -> int:
    try:
        user_id = int(user.get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    if user_id <= 0:
        raise HTTPException(status_code=401, detail="用户身份无效")
    return user_id


def _set_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _channel_payload(channel: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": channel["id"],
        "channel_type": channel["channel_type"],
        "target": channel["target"],
        "verified": channel["verified"],
        "status": channel["status"],
        "created_at": channel["created_at"],
    }


def _subscription_payload(subscription: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": subscription["id"],
        "channel_id": subscription["channel_id"],
        "channel_type": subscription["channel_type"],
        "target": subscription["target"],
        "source": subscription["source"],
        "frequency": subscription["frequency"],
        "status": subscription["status"],
        "created_at": subscription["created_at"],
    }


def _map_domain_error(exc: PushDomainError) -> HTTPException:
    if isinstance(exc, (PushChannelNotFoundError, SubscriptionNotFoundError)):
        return HTTPException(status_code=404, detail=exc.detail)
    if isinstance(exc, (PushChannelDuplicateError, SubscriptionDuplicateError)):
        return HTTPException(status_code=409, detail=exc.detail)
    if isinstance(exc, WebhookDeliveryError):
        return HTTPException(status_code=502, detail=exc.detail)
    return HTTPException(status_code=400, detail=exc.detail)


def _map_email_error(exc: Exception) -> HTTPException:
    if isinstance(exc, OtpSendRateLimitedError):
        return HTTPException(status_code=429, detail=exc.detail)
    if isinstance(exc, (OtpDeliveryUnavailableError, BriefingDeliveryError)):
        return HTTPException(status_code=503, detail=exc.detail)
    return HTTPException(status_code=500, detail="邮件服务异常")


# ---------------------------------------------------------------------------
# 推送渠道
# ---------------------------------------------------------------------------


@router.get("/push/me/channels", response_model=list[PushChannelResponse])
async def list_push_channels(
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    service: PushChannelService = Depends(get_push_channel_service),
) -> list[dict[str, Any]]:
    _set_no_store(response)
    channels = await asyncio.to_thread(
        service.list_channels,
        user_id=_user_id(current_user),
    )
    return [_channel_payload(channel) for channel in channels]


@router.post(
    "/push/me/channels",
    response_model=PushChannelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建当前用户的推送渠道（email 签发验证码；webhook 探测即验证）",
)
async def create_push_channel(
    body: CreatePushChannelRequest,
    request: Request,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    service: PushChannelService = Depends(get_push_channel_service),
) -> dict[str, Any]:
    _set_no_store(response)
    if body.channel_type == "webhook":
        await _enforce_rate_limit(
            request,
            action="push.channel_webhook",
            limit=_CHANNEL_WEBHOOK_CREATE_RATE_LIMIT,
        )
        try:
            channel, _created = await service.create_webhook_channel(
                user_id=_user_id(current_user),
                url=body.target,
                secret_box=build_push_channel_secret_box(),
                webhook_sender=WebhookSender(),
            )
        except (
            PushChannelDuplicateError,
            WebhookUrlError,
            WebhookProbeFailedError,
        ) as exc:
            raise _map_domain_error(exc) from exc
        except PushChannelSecretError as exc:
            raise HTTPException(status_code=503, detail=exc.args[0]) from exc
        return _channel_payload(channel)
    await _enforce_rate_limit(
        request, action="push.channel_otp", limit=_CHANNEL_OTP_SEND_RATE_LIMIT
    )
    try:
        channel, _created = await service.create_email_channel(
            user_id=_user_id(current_user),
            email=body.target,
            email_service=_get_email_service(request),
        )
    except (PushChannelDuplicateError,) as exc:
        raise _map_domain_error(exc) from exc
    except (OtpSendRateLimitedError, OtpDeliveryUnavailableError) as exc:
        raise _map_email_error(exc) from exc
    return _channel_payload(channel)


@router.post("/push/me/channels/{channel_id}/verify", response_model=PushChannelResponse)
async def verify_push_channel(
    channel_id: int,
    body: VerifyPushChannelRequest,
    request: Request,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    service: PushChannelService = Depends(get_push_channel_service),
) -> dict[str, Any]:
    _set_no_store(response)
    try:
        channel = await service.verify_channel(
            user_id=_user_id(current_user),
            channel_id=channel_id,
            code=body.code,
            email_service=_get_email_service(request),
        )
    except (PushChannelNotFoundError, InvalidChannelOtpError) as exc:
        raise _map_domain_error(exc) from exc
    return _channel_payload(channel)


@router.patch("/push/me/channels/{channel_id}", response_model=PushChannelResponse)
async def update_push_channel(
    channel_id: int,
    body: UpdatePushChannelRequest,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    service: PushChannelService = Depends(get_push_channel_service),
) -> dict[str, Any]:
    _set_no_store(response)
    try:
        channel = await asyncio.to_thread(
            service.set_channel_status,
            user_id=_user_id(current_user),
            channel_id=channel_id,
            status=body.status,
        )
    except PushChannelNotFoundError as exc:
        raise _map_domain_error(exc) from exc
    return _channel_payload(channel)


@router.delete("/push/me/channels/{channel_id}")
async def delete_push_channel(
    channel_id: int,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    service: PushChannelService = Depends(get_push_channel_service),
) -> dict[str, Any]:
    _set_no_store(response)
    try:
        await asyncio.to_thread(
            service.delete_channel,
            user_id=_user_id(current_user),
            channel_id=channel_id,
        )
    except PushChannelNotFoundError as exc:
        raise _map_domain_error(exc) from exc
    return {"deleted": True, "id": channel_id}


@router.post("/push/me/channels/{channel_id}/test", response_model=PushChannelResponse)
async def test_push_channel(
    channel_id: int,
    request: Request,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    service: PushChannelService = Depends(get_push_channel_service),
) -> dict[str, Any]:
    """向已验证渠道发送测试投递（email 走 SMTP；webhook 走平台载荷）。"""
    _set_no_store(response)
    await _enforce_rate_limit(
        request, action="push.channel_test", limit=_CHANNEL_TEST_RATE_LIMIT
    )
    try:
        channel = await service.send_test_message(
            user_id=_user_id(current_user),
            channel_id=channel_id,
            email_service=_get_email_service(request),
            secret_box=build_push_channel_secret_box(),
            webhook_sender=WebhookSender(),
        )
    except (
        PushChannelNotFoundError,
        PushChannelNotVerifiedError,
        PushChannelDisabledError,
        WebhookDeliveryError,
    ) as exc:
        raise _map_domain_error(exc) from exc
    except PushChannelSecretError as exc:
        raise HTTPException(status_code=503, detail=exc.args[0]) from exc
    except BriefingDeliveryError as exc:
        raise _map_email_error(exc) from exc
    return _channel_payload(channel)


# ---------------------------------------------------------------------------
# 订阅
# ---------------------------------------------------------------------------


@router.get("/push/me/subscriptions", response_model=list[SubscriptionResponse])
async def list_user_subscriptions(
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    service: UserSubscriptionService = Depends(get_user_subscription_service),
) -> list[dict[str, Any]]:
    _set_no_store(response)
    subscriptions = await asyncio.to_thread(
        service.list_subscriptions,
        user_id=_user_id(current_user),
    )
    return [_subscription_payload(subscription) for subscription in subscriptions]


@router.post(
    "/push/me/subscriptions",
    response_model=SubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建当前用户的订阅（绑定已验证渠道）",
)
async def create_user_subscription(
    body: CreateSubscriptionRequest,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    service: UserSubscriptionService = Depends(get_user_subscription_service),
) -> dict[str, Any]:
    _set_no_store(response)
    try:
        subscription = await asyncio.to_thread(
            service.create_subscription,
            user_id=_user_id(current_user),
            channel_id=body.channel_id,
            source=body.source,
            frequency=body.frequency,
        )
    except (
        PushChannelNotFoundError,
        PushChannelNotVerifiedError,
        PushChannelDisabledError,
        SubscriptionDuplicateError,
    ) as exc:
        raise _map_domain_error(exc) from exc
    return _subscription_payload(subscription)


@router.patch(
    "/push/me/subscriptions/{subscription_id}", response_model=SubscriptionResponse
)
async def update_user_subscription(
    subscription_id: int,
    body: UpdateSubscriptionRequest,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    service: UserSubscriptionService = Depends(get_user_subscription_service),
) -> dict[str, Any]:
    _set_no_store(response)
    user_id = _user_id(current_user)
    try:
        await asyncio.to_thread(
            service.set_subscription_status,
            user_id=user_id,
            subscription_id=subscription_id,
            status=body.status,
        )
    except SubscriptionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.detail) from exc
    subscriptions = await asyncio.to_thread(service.list_subscriptions, user_id=user_id)
    subscription = next(
        (item for item in subscriptions if item["id"] == subscription_id), None
    )
    if subscription is None:  # pragma: no cover - 防御性分支
        raise HTTPException(status_code=404, detail="订阅不存在")
    return _subscription_payload(subscription)


@router.delete("/push/me/subscriptions/{subscription_id}")
async def delete_user_subscription(
    subscription_id: int,
    response: Response,
    current_user: dict[str, Any] = Depends(RequireUser),
    service: UserSubscriptionService = Depends(get_user_subscription_service),
) -> dict[str, Any]:
    _set_no_store(response)
    try:
        await asyncio.to_thread(
            service.delete_subscription,
            user_id=_user_id(current_user),
            subscription_id=subscription_id,
        )
    except SubscriptionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.detail) from exc
    return {"deleted": True, "id": subscription_id}
