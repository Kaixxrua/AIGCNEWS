"""日报订阅计划聚合编排：source × delivery 一次提交、事务写入。

保持底层 ``briefing_subscriptions`` 与 ``user_subscriptions`` 存储分离，
只在上层把「选模块 + 选渠道」收敛为单一 facade，避免前端编排多次写请求。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.core.postgres_database import PostgresDatabaseLifecycle
from backend.app.repositories.briefing_repository import BriefingSubscriptionRepository
from backend.app.repositories.push_channel_repository import PushChannelRepository
from backend.app.repositories.user_subscription_repository import UserSubscriptionRepository
from backend.app.services.membership.subscription_quota import (
    SubscriptionQuotaExceededError,
    collect_active_daily_sources,
    ensure_subscription_quota,
)
from backend.app.services.membership.tiers import (
    MEMBERSHIP_TIER_MEMBER,
    resolve_effective_tier,
)
from backend.app.services.push.channel_service import CHANNEL_STATUS_ACTIVE
from backend.app.services.push.errors import (
    PushChannelDisabledError,
    PushChannelNotFoundError,
    PushChannelNotVerifiedError,
    VipRequiredError,
)

_VALID_SOURCES = {
    "all",
    "arxiv",
    "github",
    "news",
    "producthunt",
    "hackernews",
    "x",
    "dailyhot",
}
_VALID_DELIVERY_KINDS = {"account_email", "push_channel", "rss"}
_VALID_RSS_FEEDS = {"briefing"}
_COMING_SOON_CHANNEL_TYPES = {"wechat", "feishu"}


@dataclass(frozen=True)
class DeliveryTarget:
    """单个投递意图（不含 source，source 在 plan 顶层）。"""

    kind: str
    channel_id: int | None = None
    feed: str | None = None


@dataclass(frozen=True)
class AppliedDelivery:
    """投递目标应用结果。"""

    kind: str
    channel_id: int | None = None
    feed: str | None = None
    status: str = "applied"  # applied | already_active


class InvalidSubscriptionPlanError(Exception):
    """请求参数不合法或权限/渠道校验失败。"""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class ReportSubscriptionPlanService:
    """日报订阅计划服务：校验、quota、事务写入。"""

    def __init__(
        self,
        *,
        database: PostgresDatabaseLifecycle,
        briefing_subscriptions: BriefingSubscriptionRepository,
        user_subscriptions: UserSubscriptionRepository,
        push_channels: PushChannelRepository,
    ) -> None:
        self._database = database
        self._briefing_subscriptions = briefing_subscriptions
        self._user_subscriptions = user_subscriptions
        self._push_channels = push_channels

    def get_plan(self, *, user: dict[str, Any], user_id: int) -> dict[str, Any]:
        """返回当前用户可选的 source/delivery 能力与活跃状态（不含 RSS token）。"""
        can_select_multiple = self._can_select_multiple_sources(user)
        active_sources = self._collect_active_sources(user_id)
        capabilities = self._build_delivery_capabilities(user_id)
        return {
            "can_select_multiple_sources": can_select_multiple,
            "max_sources": 8 if can_select_multiple else 1,
            "active_sources": sorted(active_sources),
            "capabilities": capabilities,
        }

    def apply_plan(
        self,
        *,
        user: dict[str, Any],
        user_id: int,
        email: str,
        sources: list[str],
        deliveries: list[DeliveryTarget],
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """一次性应用 source 集合与 delivery 集合；失败时事务回滚、零写入。"""
        normalized_sources = self._normalize_sources(sources)
        if not normalized_sources:
            raise InvalidSubscriptionPlanError("请选择至少一个有效订阅领域")

        normalized_deliveries = self._normalize_deliveries(deliveries)
        if not normalized_deliveries:
            raise InvalidSubscriptionPlanError("请选择至少一种投递方式")

        if not self._can_select_multiple_sources(user) and len(normalized_sources) > 1:
            raise SubscriptionQuotaExceededError(
                "免费档最多订阅 1 个日报模块，开通会员解锁全部 8 个模块"
            )

        # 预加载渠道与现有订阅，用于校验与幂等去重
        channels_by_id = self._load_channels(user_id)
        active_push_subscriptions = self._load_active_push_subscriptions(user_id)
        active_sources = self._collect_active_sources(user_id)

        has_account_email = False
        rss_feed: str | None = None
        push_targets: list[tuple[str, int]] = []

        for delivery in normalized_deliveries:
            if delivery.kind == "account_email":
                has_account_email = True
            elif delivery.kind == "rss":
                feed = delivery.feed or "briefing"
                if feed not in _VALID_RSS_FEEDS:
                    raise InvalidSubscriptionPlanError("不支持的 RSS feed")
                rss_feed = feed
            elif delivery.kind == "push_channel":
                channel_id = delivery.channel_id
                if channel_id is None:
                    raise InvalidSubscriptionPlanError(
                        "push_channel 投递必须指定 channel_id"
                    )
                channel = channels_by_id.get(channel_id)
                self._validate_channel_for_subscription(channel, user)
                for source in normalized_sources:
                    if (source, channel_id) not in active_push_subscriptions:
                        push_targets.append((source, channel_id))
            else:
                raise InvalidSubscriptionPlanError(
                    f"不支持的投递方式: {delivery.kind}"
                )

        # 跨体系 quota 校验（admin 在 ensure_subscription_quota 内豁免）
        ensure_subscription_quota(
            tier=str(user.get("membership_tier") or "free"),
            active_sources=active_sources,
            adding_sources=set(normalized_sources),
        )

        applied: list[AppliedDelivery] = []
        with self._database.transaction() as connection:
            if has_account_email:
                for source in normalized_sources:
                    self._briefing_subscriptions.upsert_briefing_subscription(
                        user_id=user_id,
                        email=email,
                        source=source,
                        connection=connection,
                    )
                status = (
                    "already_active"
                    if active_sources.issuperset(normalized_sources)
                    else "applied"
                )
                applied.append(AppliedDelivery(kind="account_email", status=status))

            if rss_feed:
                applied.append(
                    AppliedDelivery(kind="rss", feed=rss_feed, status="applied")
                )

            for source, channel_id in push_targets:
                self._user_subscriptions.create_subscription(
                    user_id=user_id,
                    channel_id=channel_id,
                    source=source,
                    frequency="daily",
                    connection=connection,
                )

        if push_targets:
            # 同一 channel 可能订阅多个 source，按 channel 聚合返回更紧凑
            applied_channel_ids = sorted({channel_id for _, channel_id in push_targets})
            for channel_id in applied_channel_ids:
                applied.append(
                    AppliedDelivery(
                        kind="push_channel",
                        channel_id=channel_id,
                        status="applied",
                    )
                )

        return {
            "sources": normalized_sources,
            "deliveries": [
                {
                    "kind": d.kind,
                    "channel_id": d.channel_id,
                    "feed": d.feed,
                    "status": d.status,
                }
                for d in applied
            ],
            "idempotency_key": idempotency_key,
        }

    @staticmethod
    def _can_select_multiple_sources(user: dict[str, Any]) -> bool:
        """admin 与当前有效会员可多选；过期会员按 free 处理。"""
        if user.get("role") == "admin":
            return True
        return (
            resolve_effective_tier(
                user.get("membership_tier"), user.get("membership_expires_at")
            )
            == MEMBERSHIP_TIER_MEMBER
        )

    def _collect_active_sources(self, user_id: int) -> set[str]:
        return collect_active_daily_sources(
            briefing_subscriptions=self._briefing_subscriptions,
            user_subscriptions=self._user_subscriptions,
            user_id=user_id,
        )

    def _normalize_sources(self, sources: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for source in sources:
            if source in _VALID_SOURCES and source not in seen:
                seen.add(source)
                result.append(source)
        return result

    def _normalize_deliveries(
        self, deliveries: list[DeliveryTarget]
    ) -> list[DeliveryTarget]:
        seen: set[tuple[str, int | None, str | None]] = set()
        result: list[DeliveryTarget] = []
        for delivery in deliveries:
            key = (delivery.kind, delivery.channel_id, delivery.feed)
            if delivery.kind in _VALID_DELIVERY_KINDS and key not in seen:
                seen.add(key)
                result.append(delivery)
        return result

    def _load_channels(self, user_id: int) -> dict[int, dict[str, Any]]:
        return {channel["id"]: channel for channel in self._push_channels.list_channels(user_id)}

    def _load_active_push_subscriptions(self, user_id: int) -> set[tuple[str, int]]:
        return {
            (str(row["source"]), int(row["channel_id"]))
            for row in self._user_subscriptions.list_subscriptions(user_id)
            if row.get("status") == "active"
        }

    def _validate_channel_for_subscription(
        self, channel: dict[str, Any] | None, user: dict[str, Any]
    ) -> None:
        if channel is None:
            raise PushChannelNotFoundError("推送渠道不存在")
        channel_type = str(channel.get("channel_type") or "")
        if channel_type in _COMING_SOON_CHANNEL_TYPES:
            raise InvalidSubscriptionPlanError(
                f"{channel_type} 渠道暂未开放"
            )
        if channel_type in {"discord", "telegram"}:
            if user.get("role") != "admin" and resolve_effective_tier(
                user.get("membership_tier"), user.get("membership_expires_at")
            ) != MEMBERSHIP_TIER_MEMBER:
                raise VipRequiredError("当前功能仅对有效会员开放")
        if not channel.get("verified"):
            raise PushChannelNotVerifiedError("推送渠道尚未验证")
        if channel.get("status") != CHANNEL_STATUS_ACTIVE:
            raise PushChannelDisabledError("推送渠道已停用")

    def _build_delivery_capabilities(self, user_id: int) -> list[dict[str, Any]]:
        """构造前端可用的 delivery 能力列表；RSS/注册邮箱始终可见，机器人仅来自已验证渠道。

        微信、飞书作为明确不可用项返回，让 UI 以灰色展示并附带原因；
        服务端同样 fail-closed，不依赖前端灰度。
        """
        capabilities: list[dict[str, Any]] = [
            {
                "kind": "rss",
                "key": "rss-briefing",
                "feed": "briefing",
                "selectable": True,
                "disabled_reason": None,
            },
            {
                "kind": "account_email",
                "key": "account-email",
                "selectable": True,
                "disabled_reason": None,
            },
        ]

        for channel in self._push_channels.list_channels(user_id):
            channel_type = str(channel.get("channel_type") or "")
            if channel_type in _COMING_SOON_CHANNEL_TYPES:
                continue
            selectable = bool(channel.get("verified")) and channel.get("status") == CHANNEL_STATUS_ACTIVE
            disabled_reason: str | None = None
            if not channel.get("verified"):
                disabled_reason = "渠道尚未验证"
            elif channel.get("status") != CHANNEL_STATUS_ACTIVE:
                disabled_reason = "渠道已停用"
            capabilities.append(
                {
                    "kind": "push_channel",
                    "key": f"push-{channel_type}-{channel['id']}",
                    "channel_id": channel["id"],
                    "channel_type": channel_type,
                    "target": self._mask_target(channel),
                    "verified": bool(channel.get("verified")),
                    "status": channel.get("status"),
                    "selectable": selectable,
                    "disabled_reason": disabled_reason,
                }
            )

        for channel_type in sorted(_COMING_SOON_CHANNEL_TYPES):
            capabilities.append(
                {
                    "kind": "push_channel",
                    "key": f"push-{channel_type}-coming-soon",
                    "channel_type": channel_type,
                    "target": None,
                    "verified": False,
                    "status": "coming_soon",
                    "selectable": False,
                    "disabled_reason": "暂未开放",
                }
            )

        return capabilities

    @staticmethod
    def _mask_target(channel: dict[str, Any]) -> str:
        target = str(channel.get("target") or "")
        channel_type = str(channel.get("channel_type") or "")
        if channel_type == "email" and "@" in target:
            local, domain = target.rsplit("@", 1)
            masked = local[:2] + "***@" + domain
            return masked
        if len(target) > 12:
            return target[:6] + "***" + target[-6:]
        return target
