"""订阅简报派发：枚举频率 × 来源读取简报缓存，经 push_deliveries 幂等投递。

与每日简报生成解耦：只读取 briefings 缓存（daily 由 8:00 生成任务填充），
内容缺失时跳过该期，不触发生成。简报仅按日生成，订阅频率只保留 daily。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any, get_args

from backend.app.models.schema_push import SubscriptionFrequency
from backend.app.repositories.briefing_repository import BriefingContentRepository
from backend.app.repositories.push_delivery_repository import PushDeliveryRepository
from backend.app.repositories.user_subscription_repository import (
    UserSubscriptionRepository,
)
from backend.app.services.briefing.daily_briefing import select_briefing_content
from backend.app.services.email.message_renderer import SOURCE_LABELS
from backend.app.services.push.channel_service import (
    CHANNEL_TYPE_EMAIL,
    CHANNEL_TYPE_WEBHOOK,
)
from backend.app.services.push.secrets import unseal_channel_config
from backend.app.services.push.webhook_service import WebhookSender

logger = logging.getLogger(__name__)

MAX_DELIVERY_ATTEMPTS = 3
DEFAULT_LOCALE = "zh-CN"

_FREQUENCIES: tuple[str, ...] = tuple(get_args(SubscriptionFrequency))
_SUPPORTED_CHANNEL_TYPES = frozenset({CHANNEL_TYPE_EMAIL, CHANNEL_TYPE_WEBHOOK})
_PERIOD_LABELS = {"daily": "日报"}
_SECRET_BOX_UNSET = object()


def _webhook_title(source: str, frequency: str, issue_date: str) -> str:
    source_label = SOURCE_LABELS.get(source, source)
    period_label = _PERIOD_LABELS.get(frequency, frequency)
    return f"AIGC Radar · {source_label}{period_label} · {issue_date}"


class SubscriptionDispatchService:
    """全频率订阅派发；单次运行对每个订阅至多尝试一次投递。"""

    def __init__(
        self,
        *,
        subscriptions: UserSubscriptionRepository,
        deliveries: PushDeliveryRepository,
        briefings: BriefingContentRepository,
        email_service: Any | None = None,
        secret_box: Any = _SECRET_BOX_UNSET,
        webhook_sender: Any | None = None,
    ) -> None:
        self._subscriptions = subscriptions
        self._deliveries = deliveries
        self._briefings = briefings
        self._email_service = email_service
        self._secret_box = secret_box
        self._webhook_sender = webhook_sender

    async def dispatch_all(self, *, today: date | None = None) -> dict[str, int]:
        """枚举全部频率与来源执行一轮派发，返回计数摘要。"""
        today = today or date.today()
        summary = {"sent": 0, "skipped": 0, "failed": 0}
        for frequency in _FREQUENCIES:
            result = await self._dispatch_frequency(frequency, today)
            for key in summary:
                summary[key] += result[key]
        return summary

    async def _dispatch_frequency(
        self,
        frequency: str,
        today: date,
    ) -> dict[str, int]:
        summary = {"sent": 0, "skipped": 0, "failed": 0}
        subscriptions = await asyncio.to_thread(
            self._subscriptions.list_active_dispatchable, frequency=frequency
        )
        if not subscriptions:
            return summary

        by_source: dict[str, list[dict[str, Any]]] = {}
        for subscription in subscriptions:
            by_source.setdefault(subscription["source"], []).append(subscription)

        issue_date = today.isoformat()
        for source, source_subscriptions in by_source.items():
            suffix = "" if source == "all" else f"_{source}"
            cache_key = f"{issue_date}{suffix}"
            briefing = await asyncio.to_thread(
                self._briefings.get_briefing_by_date, cache_key
            )
            if not briefing:
                continue
            content = select_briefing_content(briefing, DEFAULT_LOCALE)
            if not content:
                continue
            for subscription in source_subscriptions:
                outcome = await self._deliver_one(
                    subscription=subscription,
                    item_key=cache_key,
                    content=content,
                    source=source,
                    frequency=frequency,
                    issue_date=issue_date,
                )
                summary[outcome] += 1
        return summary

    async def _deliver_one(
        self,
        *,
        subscription: dict[str, Any],
        item_key: str,
        content: str,
        source: str,
        frequency: str,
        issue_date: str,
    ) -> str:
        """对单个订阅执行一次投递，返回 sent / skipped / failed。"""
        subscription_id = subscription["id"]
        channel_type = subscription["channel_type"]
        if channel_type not in _SUPPORTED_CHANNEL_TYPES:
            logger.warning(
                "[Dispatch] 暂不支持的渠道类型: channel_type=%s subscription=%s",
                channel_type,
                subscription_id,
            )
            return "skipped"

        delivery = await asyncio.to_thread(
            self._deliveries.get_delivery,
            subscription_id=subscription_id,
            item_key=item_key,
        )
        if delivery is not None and delivery["status"] != "pending":
            return "skipped"
        if delivery is not None and delivery["attempts"] >= MAX_DELIVERY_ATTEMPTS:
            # 兜底：正常流程下尝试次数用尽时已置 failed 终态。
            return "skipped"
        if delivery is None:
            delivery = await asyncio.to_thread(
                self._deliveries.create_delivery,
                subscription_id=subscription_id,
                item_key=item_key,
            )
            if delivery is None:
                # 并发派发已抢占该期；以现况为准。
                delivery = await asyncio.to_thread(
                    self._deliveries.get_delivery,
                    subscription_id=subscription_id,
                    item_key=item_key,
                )
                if delivery is None or delivery["status"] != "pending":
                    return "skipped"

        attempts_next = delivery["attempts"] + 1
        try:
            await self._send(
                subscription=subscription,
                content=content,
                source=source,
                frequency=frequency,
                issue_date=issue_date,
            )
        except Exception as exc:
            await asyncio.to_thread(
                self._deliveries.record_attempt_failed,
                delivery_id=delivery["id"],
                attempts=attempts_next,
                last_error=str(exc),
                exhausted=attempts_next >= MAX_DELIVERY_ATTEMPTS,
            )
            logger.error(
                "[Dispatch] 订阅投递失败: subscription=%s item=%s attempts=%s error=%s",
                subscription_id,
                item_key,
                attempts_next,
                exc,
                exc_info=True,
            )
            return "failed"

        await asyncio.to_thread(
            self._deliveries.mark_delivery_sent,
            delivery_id=delivery["id"],
            attempts=attempts_next,
        )
        return "sent"

    async def _send(
        self,
        *,
        subscription: dict[str, Any],
        content: str,
        source: str,
        frequency: str,
        issue_date: str,
    ) -> None:
        """按渠道类型执行一次真实投递；失败抛异常由调用方记账。"""
        if subscription["channel_type"] == CHANNEL_TYPE_EMAIL:
            email_service = self._resolve_email_service()
            await email_service.send_briefing(
                to_email=subscription["target"],
                briefing_content=content,
                source=source,
                period=frequency,
                date_str=issue_date,
            )
            return
        # webhook：投递凭据以密封配置为准（target 仅作地址展示与唯一约束）。
        config = await asyncio.to_thread(
            unseal_channel_config,
            self._resolve_secret_box(),
            subscription.get("encrypted_config") or "",
        )
        sender = self._resolve_webhook_sender()
        await sender.send(
            url=str(config.get("url") or ""),
            title=_webhook_title(source, frequency, issue_date),
            content=content,
        )

    def _resolve_secret_box(self) -> Any:
        if self._secret_box is _SECRET_BOX_UNSET:
            # 未注入时按当前配置即时构建（对齐 email_service 惯例）；
            # 显式注入 None 表示密钥不可用，unseal 处拒绝并计入失败。
            from backend.app.services.push.secrets import (
                build_push_channel_secret_box,
            )

            self._secret_box = build_push_channel_secret_box()
        return self._secret_box

    def _resolve_webhook_sender(self) -> Any:
        if self._webhook_sender is None:
            self._webhook_sender = WebhookSender()
        return self._webhook_sender

    def _resolve_email_service(self) -> Any:
        if self._email_service is None:
            # 与调度器既有惯例一致：未注入时按当前配置即时构建。
            from backend.app.services.email_service import build_email_service

            self._email_service = build_email_service(None)
        return self._email_service
