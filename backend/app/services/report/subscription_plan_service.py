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
        """返回当前用户可选的 source/delivery 能力与活跃状态（不含 RSS token）。

        capability.active 供前端向导预选：account_email 有活跃简报订阅、
        push_channel 有活跃订阅时为 True；RSS 无服务端记录，恒为 False。
        """
        can_select_multiple = self._can_select_multiple_sources(user)
        briefing_rows = self._briefing_subscriptions.get_user_briefing_subscriptions(
            user_id
        )
        push_rows = self._user_subscriptions.list_subscriptions(user_id)
        active_sources = self._collect_active_sources_from_rows(
            briefing_rows, push_rows
        )
        active_push_channel_ids = {
            int(row["channel_id"])
            for row in push_rows
            if row.get("status") == "active"
        }
        capabilities = self._build_delivery_capabilities(
            user_id,
            account_email_active=bool(briefing_rows),
            active_push_channel_ids=active_push_channel_ids,
        )
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
        sync: bool = False,
    ) -> dict[str, Any]:
        """一次性应用 source 集合与 delivery 集合；失败时事务回滚、零写入。

        sync=False（默认，旧契约）：纯增量，只新增/幂等跳过，不做任何移除。
        sync=True：把用户日报订阅同步为「sources × deliveries」的笛卡尔积——
        未选中的活跃 source/渠道订阅在同一事务内移除（briefing 软取消、
        user_subscriptions 硬删，与既有 unsubscribe/delete 路由语义一致），
        期望对中的 paused 行恢复为 active。sources 与 deliveries 同时为空表示
        全部退订；仅一边为空语义含混，拒绝。quota 按移除后的最终集合校验，
        免费档换模块（A→B）不被存量误伤。
        """
        normalized_sources = self._normalize_sources(sources)
        normalized_deliveries = self._normalize_deliveries(deliveries)

        if sync:
            if bool(normalized_sources) != bool(normalized_deliveries):
                raise InvalidSubscriptionPlanError(
                    "同步模式下订阅领域与投递方式需同时为空（全部退订）或同时非空"
                )
        else:
            if not normalized_sources:
                raise InvalidSubscriptionPlanError("请选择至少一个有效订阅领域")
            if not normalized_deliveries:
                raise InvalidSubscriptionPlanError("请选择至少一种投递方式")

        if not self._can_select_multiple_sources(user) and len(normalized_sources) > 1:
            raise SubscriptionQuotaExceededError(
                "免费档最多订阅 1 个日报模块，开通会员解锁全部 8 个模块"
            )

        # 预加载渠道与现有订阅，用于校验、幂等去重与 sync 移除
        channels_by_id = self._load_channels(user_id)
        briefing_rows = self._briefing_subscriptions.get_user_briefing_subscriptions(
            user_id
        )
        push_rows = self._user_subscriptions.list_subscriptions(user_id)
        active_sources = self._collect_active_sources_from_rows(
            briefing_rows, push_rows
        )
        active_push_subscriptions = {
            (str(row["source"]), int(row["channel_id"]))
            for row in push_rows
            if row.get("status") == "active"
        }
        existing_push_pairs = {
            (str(row["source"]), int(row["channel_id"])) for row in push_rows
        }

        has_account_email = False
        rss_feed: str | None = None
        selected_push_channel_ids: list[int] = []
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
                selected_push_channel_ids.append(channel_id)
                for source in normalized_sources:
                    # sync 模式按「无任何存量行」判定新增（paused 行稍后恢复），
                    # 增量模式维持旧语义：仅跳过已活跃对。
                    known_pairs = (
                        existing_push_pairs if sync else active_push_subscriptions
                    )
                    if (source, channel_id) not in known_pairs:
                        push_targets.append((source, channel_id))
            else:
                raise InvalidSubscriptionPlanError(
                    f"不支持的投递方式: {delivery.kind}"
                )

        # 跨体系 quota 校验（admin 在 ensure_subscription_quota 内豁免）；
        # sync 模式先扣除将被移除的存量，按最终集合校验，免费档换模块不被误伤。
        desired_source_set = set(normalized_sources)
        ensure_subscription_quota(
            tier=str(user.get("membership_tier") or "free"),
            active_sources=(
                active_sources & desired_source_set if sync else active_sources
            ),
            adding_sources=desired_source_set,
        )

        desired_push_pairs = {
            (source, channel_id)
            for source in normalized_sources
            for channel_id in selected_push_channel_ids
        }
        removed_sources = (
            active_sources - desired_source_set if sync else set()
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

            if sync:
                self._apply_sync_removals(
                    user_id=user_id,
                    briefing_rows=briefing_rows,
                    push_rows=push_rows,
                    keep_briefing=has_account_email,
                    desired_source_set=desired_source_set,
                    desired_push_pairs=desired_push_pairs,
                    connection=connection,
                )

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
            "removed_sources": sorted(removed_sources),
            "idempotency_key": idempotency_key,
        }

    def _apply_sync_removals(
        self,
        *,
        user_id: int,
        briefing_rows: list[dict[str, Any]],
        push_rows: list[dict[str, Any]],
        keep_briefing: bool,
        desired_source_set: set[str],
        desired_push_pairs: set[tuple[str, int]],
        connection: Any,
    ) -> None:
        """sync 模式的移除与恢复：在调用方事务内执行。

        briefing：未选中 source 的活跃行软取消；未选 account_email 时全部取消。
        push：不在期望对中的行（含 paused）硬删，与既有 delete 路由语义一致；
        期望对中的 paused 行恢复为 active——向导勾选即「我要它生效」。
        """
        for row in briefing_rows:
            source = str(row.get("source") or "")
            if not source:
                continue
            if not keep_briefing or source not in desired_source_set:
                self._briefing_subscriptions.cancel_briefing_subscription(
                    user_id=user_id,
                    source=source,
                    connection=connection,
                )
        for row in push_rows:
            pair = (str(row.get("source") or ""), int(row["channel_id"]))
            if pair not in desired_push_pairs:
                self._user_subscriptions.delete_subscription(
                    user_id=user_id,
                    subscription_id=int(row["id"]),
                    connection=connection,
                )
            elif row.get("status") != "active":
                self._user_subscriptions.set_subscription_status(
                    user_id=user_id,
                    subscription_id=int(row["id"]),
                    status="active",
                    connection=connection,
                )

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

    @staticmethod
    def _collect_active_sources_from_rows(
        briefing_rows: list[dict[str, Any]],
        push_rows: list[dict[str, Any]],
    ) -> set[str]:
        """跨体系合计活跃日报模块；口径与 subscription_quota.collect_active_daily_sources 一致。"""
        sources = {
            str(row["source"]) for row in briefing_rows if row.get("source")
        }
        sources.update(
            str(row["source"])
            for row in push_rows
            if row.get("source")
            and row.get("status") == "active"
            and row.get("frequency", "daily") == "daily"
        )
        return sources

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

    def _build_delivery_capabilities(
        self,
        user_id: int,
        *,
        account_email_active: bool = False,
        active_push_channel_ids: set[int] | None = None,
    ) -> list[dict[str, Any]]:
        """构造前端可用的 delivery 能力列表；RSS/注册邮箱始终可见，机器人仅来自已验证渠道。

        微信、飞书作为明确不可用项返回，让 UI 以灰色展示并附带原因；
        服务端同样 fail-closed，不依赖前端灰度。active 标记供向导预选
        当前已生效的投递方式（RSS 无服务端记录，恒为 False）。
        """
        active_push_channel_ids = active_push_channel_ids or set()
        capabilities: list[dict[str, Any]] = [
            {
                "kind": "rss",
                "key": "rss-briefing",
                "feed": "briefing",
                "selectable": True,
                "disabled_reason": None,
                "active": False,
            },
            {
                "kind": "account_email",
                "key": "account-email",
                "selectable": True,
                "disabled_reason": None,
                "active": account_email_active,
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
                    "active": channel["id"] in active_push_channel_ids,
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
                    "active": False,
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
