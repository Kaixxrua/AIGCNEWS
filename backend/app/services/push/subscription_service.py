"""用户订阅的领域编排：渠道校验前置 + 订阅 CRUD。"""

from __future__ import annotations

from typing import Any, get_args

from backend.app.models.schema_push import SubscriptionFrequency, SubscriptionSource
from backend.app.repositories.postgres_user_subscription_repository import (
    SubscriptionChannelMissingError,
)
from backend.app.repositories.push_channel_repository import PushChannelRepository
from backend.app.repositories.user_subscription_repository import (
    UserSubscriptionRepository,
)
from backend.app.services.membership.tiers import MEMBERSHIP_TIER_MEMBER, resolve_effective_tier
from backend.app.services.push.channel_service import (
    CHANNEL_STATUS_ACTIVE,
    CHANNEL_TYPE_DISCORD,
    CHANNEL_TYPE_TELEGRAM,
)
from backend.app.services.push.errors import (
    PushChannelDisabledError,
    PushChannelNotFoundError,
    PushChannelNotVerifiedError,
    SubscriptionDuplicateError,
    SubscriptionNotFoundError,
    VipRequiredError,
)

SUBSCRIPTION_STATUS_ACTIVE = "active"
SUBSCRIPTION_STATUS_PAUSED = "paused"

# 词汇表的权威定义在 API schema 层，此处派生供服务与测试断言使用。
SUBSCRIPTION_SOURCES = get_args(SubscriptionSource)
SUBSCRIPTION_FREQUENCIES = get_args(SubscriptionFrequency)


class UserSubscriptionService:
    """用户订阅的领域服务；仓储调用为同步，由路由层转移到线程池。"""

    def __init__(
        self,
        subscriptions: UserSubscriptionRepository,
        channels: PushChannelRepository,
    ) -> None:
        self._subscriptions = subscriptions
        self._channels = channels

    def create_subscription(
        self,
        *,
        user_id: int,
        channel_id: int,
        source: str,
        frequency: str,
        current_user: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        channel = self._channels.get_channel(user_id=user_id, channel_id=channel_id)
        if channel is None:
            raise PushChannelNotFoundError("推送渠道不存在")
        if channel["channel_type"] in {CHANNEL_TYPE_DISCORD, CHANNEL_TYPE_TELEGRAM}:
            user = current_user or {}
            if user.get("role") != "admin" and resolve_effective_tier(
                user.get("membership_tier"), user.get("membership_expires_at")
            ) != MEMBERSHIP_TIER_MEMBER:
                raise VipRequiredError("当前功能仅对有效会员开放")
        if not channel["verified"]:
            raise PushChannelNotVerifiedError("推送渠道尚未验证")
        if channel["status"] != CHANNEL_STATUS_ACTIVE:
            raise PushChannelDisabledError("推送渠道已停用")
        try:
            subscription = self._subscriptions.create_subscription(
                user_id=user_id,
                channel_id=channel_id,
                source=source,
                frequency=frequency,
            )
        except SubscriptionChannelMissingError as exc:
            # 渠道在校验与插入之间被删除。
            raise PushChannelNotFoundError("推送渠道不存在") from exc
        if subscription is None:
            raise SubscriptionDuplicateError("该渠道下已存在相同来源与频率的订阅")
        subscription["channel_type"] = channel["channel_type"]
        subscription["target"] = channel["target"]
        return subscription

    def list_subscriptions(self, *, user_id: int) -> list[dict[str, Any]]:
        return self._subscriptions.list_subscriptions(user_id)

    def set_subscription_status(
        self,
        *,
        user_id: int,
        subscription_id: int,
        status: str,
        current_user: dict[str, Any] | None = None,
    ) -> None:
        if status == "active" and current_user is not None:
            existing = next(
                (row for row in self._subscriptions.list_subscriptions(user_id)
                 if row["id"] == subscription_id),
                None,
            )
            if existing and existing["channel_type"] in {CHANNEL_TYPE_DISCORD, CHANNEL_TYPE_TELEGRAM}:
                if current_user.get("role") != "admin" and resolve_effective_tier(
                    current_user.get("membership_tier"), current_user.get("membership_expires_at")
                ) != MEMBERSHIP_TIER_MEMBER:
                    raise VipRequiredError("当前功能仅对有效会员开放")
        updated = self._subscriptions.set_subscription_status(
            user_id=user_id,
            subscription_id=subscription_id,
            status=status,
        )
        if not updated:
            raise SubscriptionNotFoundError("订阅不存在")

    def delete_subscription(self, *, user_id: int, subscription_id: int) -> None:
        deleted = self._subscriptions.delete_subscription(
            user_id=user_id,
            subscription_id=subscription_id,
        )
        if not deleted:
            raise SubscriptionNotFoundError("订阅不存在")
