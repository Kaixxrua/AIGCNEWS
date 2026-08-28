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
from backend.app.services.briefing.daily_briefing import (
    get_briefing_cache_key,
    select_briefing_content,
)
from backend.app.services.email.message_renderer import SOURCE_LABELS
from backend.app.services.ingestion.base_crawler import today_cst
from backend.app.services.membership.tiers import (
    MEMBERSHIP_TIER_MEMBER,
    resolve_effective_tier,
)
from backend.app.services.push.channel_service import (
    CHANNEL_TYPE_DISCORD,
    CHANNEL_TYPE_EMAIL,
    CHANNEL_TYPE_TELEGRAM,
    CHANNEL_TYPE_WEBHOOK,
)
from backend.app.services.push.errors import TelegramNotConfiguredError
from backend.app.services.push.secrets import unseal_channel_config
from backend.app.services.push.webhook_service import WebhookSender

logger = logging.getLogger(__name__)

MAX_DELIVERY_ATTEMPTS = 3
DEFAULT_LOCALE = "zh-CN"

_FREQUENCIES: tuple[str, ...] = tuple(get_args(SubscriptionFrequency))
_SUPPORTED_CHANNEL_TYPES = frozenset(
    {
        CHANNEL_TYPE_EMAIL,
        CHANNEL_TYPE_WEBHOOK,
        CHANNEL_TYPE_DISCORD,
        CHANNEL_TYPE_TELEGRAM,
    }
)
# 直投渠道（bot/webhook 类）要求当前有效会员；到期只暂停派发，
# 不删渠道/订阅，权益恢复后下一轮自然接续。
_DIRECT_CHANNEL_TYPES = frozenset(
    {CHANNEL_TYPE_WEBHOOK, CHANNEL_TYPE_DISCORD, CHANNEL_TYPE_TELEGRAM}
)
_PERIOD_LABELS = {"daily": "日报"}
_SECRET_BOX_UNSET = object()
_EMAIL_SERVICE_UNSET = object()


def _webhook_title(source: str, frequency: str, issue_date: str) -> str:
    source_label = SOURCE_LABELS.get(source, source)
    period_label = _PERIOD_LABELS.get(frequency, frequency)
    return f"AIGC Radar · {source_label}{period_label} · {issue_date}"


def _direct_dispatch_allowed(subscription: dict[str, Any]) -> bool:
    """直投渠道派发门禁：admin 或当前有效 member；其余（含过期 member）暂停。

    会员抑制不是 provider failure：不创建 delivery、不计 attempts。
    派发查询（list_active_dispatchable）负责带出 role/membership 字段。
    """
    if subscription.get("role") == "admin":
        return True
    tier = resolve_effective_tier(
        subscription.get("membership_tier"),
        subscription.get("membership_expires_at"),
    )
    return tier == MEMBERSHIP_TIER_MEMBER


class SubscriptionDispatchService:
    """全频率订阅派发；单次运行对每个订阅至多尝试一次投递。"""

    def __init__(
        self,
        *,
        subscriptions: UserSubscriptionRepository,
        deliveries: PushDeliveryRepository,
        briefings: BriefingContentRepository,
        email_service: Any = _EMAIL_SERVICE_UNSET,
        secret_box: Any = _SECRET_BOX_UNSET,
        webhook_sender: Any | None = None,
        telegram_sender: Any | None = None,
        # 邮件池配额计数/熔断依赖 Redis；None 时护栏 fail-open（仅纯 failover）。
        redis_client: Any | None = None,
    ) -> None:
        self._subscriptions = subscriptions
        self._deliveries = deliveries
        self._briefings = briefings
        self._email_service = email_service
        self._secret_box = secret_box
        self._webhook_sender = webhook_sender
        self._telegram_sender = telegram_sender
        self._redis_client = redis_client

    async def dispatch_all(self, *, today: date | None = None) -> dict[str, int]:
        """枚举全部频率与来源执行一轮派发，返回计数摘要。"""
        # 简报缓存键按 CST（UTC+8）日期生成，缺省日期必须同口径，
        # 否则服务器位于非 +8 时区时在 0 点后会读错一期。
        today = today or date.fromisoformat(today_cst())
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
            # 缓存键统一走 get_briefing_cache_key：X 的实际键是
            # YYYY-MM-DD_0800_x（固定 08:00 锚点），手工拼接 _x 后缀会读不到。
            cache_key = get_briefing_cache_key(issue_date, source)
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

    async def dispatch_issue(
        self,
        *,
        source: str,
        report_date: str,
        content: str,
    ) -> dict[str, int]:
        """对已保存的指定一期执行 email-only 定向补发。

        用于简报手动生成（报告页 SSE / 运维 generate-all）成功后的自动补发：
        正文由调用方直接携带，不读缓存、不触发生成、不扫描其他来源。
        webhook/Discord/Telegram 不纳入本入口，仍由调度轮询 dispatch_all 负责；
        幂等与重试沿用 (subscription_id, item_key) delivery 台账，
        item_key 即完整简报缓存键（X 为 {report_date}_0800_x）。
        """
        summary = {"sent": 0, "skipped": 0, "failed": 0}
        if not content.strip() or not report_date:
            return summary
        subscriptions = await asyncio.to_thread(
            self._subscriptions.list_active_dispatchable, frequency="daily"
        )
        if not subscriptions:
            return summary
        item_key = get_briefing_cache_key(report_date, source)
        for subscription in subscriptions:
            if subscription["source"] != source:
                continue
            if subscription["channel_type"] != CHANNEL_TYPE_EMAIL:
                # 自动补发只面向邮箱；其他渠道留给调度轮询，这里连台账都不建。
                continue
            outcome = await self._deliver_one(
                subscription=subscription,
                item_key=item_key,
                content=content,
                source=source,
                frequency="daily",
                issue_date=report_date,
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
        if channel_type in _DIRECT_CHANNEL_TYPES and not _direct_dispatch_allowed(
            subscription
        ):
            logger.info(
                "[Dispatch] 会员权益失效，暂停直投渠道派发: subscription=%s channel_type=%s",
                subscription_id,
                channel_type,
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
        # 直投渠道：投递凭据以密封配置为准（target 仅作展示与唯一约束）。
        config = await asyncio.to_thread(
            unseal_channel_config,
            self._resolve_secret_box(),
            subscription.get("encrypted_config") or "",
        )
        if subscription["channel_type"] == CHANNEL_TYPE_TELEGRAM:
            sender = self._resolve_telegram_sender()
            await sender.send_message(
                chat_id=str(config.get("chat_id") or ""),
                title=_webhook_title(source, frequency, issue_date),
                content=content,
            )
            return
        # webhook/discord：同走平台化 webhook 载荷（discord 原生 content 格式）
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

    def _resolve_telegram_sender(self) -> Any:
        if self._telegram_sender is None:
            # build_telegram_bot_client 内部走 resolve_telegram_config：DB 行
            # 覆盖 env、60s TTL 热生效（口径同 _resolve_email_service 的 SMTP）。
            # 实例级缓存无需打破——本 service 活不过一轮派发，热生效上界即
            # 一轮调度周期。未启用/未配置 token 时按领域错误计入失败（文案
            # 静态，不含凭据）。
            from backend.app.services.push.telegram_service import (
                build_telegram_bot_client,
            )

            client = build_telegram_bot_client()
            if client is None:
                raise TelegramNotConfiguredError("Telegram 推送未启用")
            self._telegram_sender = client
        return self._telegram_sender

    def _resolve_email_service(self) -> Any:
        if self._email_service is _EMAIL_SERVICE_UNSET:
            # 未注入时每次发送按当前生效配置即时构建：SMTP 配置入 DB 后
            # 免重启热生效（provider 60s TTL 限制 DB 读取频率），不再
            # 永久缓存实例。显式注入（测试 fake）仍优先。
            # redis_client 供邮件池配额计数与熔断；None 时护栏 fail-open。
            from backend.app.services.email_service import build_email_service

            return build_email_service(self._redis_client)
        return self._email_service
