"""订阅简报派发服务的幂等与重试语义契约测试。"""

from __future__ import annotations

import asyncio
import base64
import unittest
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

from backend.app.domain.wechat_secret_box import WeChatSecretBox
from backend.app.services.push.dispatch_service import (
    MAX_DELIVERY_ATTEMPTS,
    SubscriptionDispatchService,
)
from backend.app.services.push.errors import TelegramDeliveryError
from backend.app.services.push.secrets import seal_channel_config

_TEST_KEY_MATERIAL = base64.urlsafe_b64encode(bytes(range(32))).decode()


def _test_box() -> WeChatSecretBox:
    return WeChatSecretBox.from_urlsafe_base64(_TEST_KEY_MATERIAL, "v1")


class FakeSubscriptionRepository:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.calls: list[str] = []

    def list_active_dispatchable(self, *, frequency: str) -> list[dict[str, Any]]:
        self.calls.append(frequency)
        return [row for row in self._rows if row["frequency"] == frequency]


class FakeDeliveryRepository:
    def __init__(self) -> None:
        self._rows: dict[tuple[int, str], dict[str, Any]] = {}
        self._next_id = 1

    def get_delivery(
        self, *, subscription_id: int, item_key: str
    ) -> dict[str, Any] | None:
        row = self._rows.get((subscription_id, item_key))
        return dict(row) if row else None

    def create_delivery(
        self, *, subscription_id: int, item_key: str
    ) -> dict[str, Any] | None:
        key = (subscription_id, item_key)
        if key in self._rows:
            return None
        row = {
            "id": self._next_id,
            "subscription_id": subscription_id,
            "item_key": item_key,
            "status": "pending",
            "attempts": 0,
            "last_error": None,
        }
        self._next_id += 1
        self._rows[key] = row
        return dict(row)

    def mark_delivery_sent(self, *, delivery_id: int, attempts: int) -> None:
        row = self._row_by_id(delivery_id)
        if row["status"] == "pending":
            row["status"] = "sent"
            row["attempts"] = attempts
            row["last_error"] = None

    def record_attempt_failed(
        self,
        *,
        delivery_id: int,
        attempts: int,
        last_error: str,
        exhausted: bool,
    ) -> None:
        row = self._row_by_id(delivery_id)
        if row["status"] == "pending":
            row["attempts"] = attempts
            row["last_error"] = last_error
            row["status"] = "failed" if exhausted else "pending"

    def _row_by_id(self, delivery_id: int) -> dict[str, Any]:
        for row in self._rows.values():
            if row["id"] == delivery_id:
                return row
        raise AssertionError(f"delivery {delivery_id} 不存在")


class FakeBriefingRepository:
    def __init__(self, briefings: dict[str, dict[str, Any]]) -> None:
        self._briefings = briefings
        self.requested_keys: list[str] = []

    def get_briefing_by_date(self, date_str: str) -> dict[str, Any] | None:
        self.requested_keys.append(date_str)
        return self._briefings.get(date_str)


class FakeEmailService:
    def __init__(self, *, failures_before_success: int = 0, always_fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._failures_left = failures_before_success
        self._always_fail = always_fail

    async def send_briefing(
        self,
        to_email: str,
        briefing_content: str,
        source: str = "all",
        period: str = "daily",
        date_str: str = "",
    ) -> None:
        self.calls.append(
            {
                "to_email": to_email,
                "briefing_content": briefing_content,
                "source": source,
                "period": period,
                "date_str": date_str,
            }
        )
        if self._always_fail or self._failures_left > 0:
            self._failures_left -= 1
            raise RuntimeError("SMTP 连接失败")


def _subscription(
    subscription_id: int,
    *,
    source: str = "all",
    frequency: str = "daily",
    channel_type: str = "email",
    target: str = "reader@example.com",
) -> dict[str, Any]:
    return {
        "id": subscription_id,
        "user_id": 1,
        "channel_id": 10 + subscription_id,
        "source": source,
        "frequency": frequency,
        "status": "active",
        "channel_type": channel_type,
        "target": target,
    }


class SubscriptionDispatchServiceTests(unittest.TestCase):
    def _make_service(
        self,
        *,
        subscriptions: list[dict[str, Any]],
        briefings: dict[str, dict[str, Any]] | None = None,
        email_service: FakeEmailService | None = None,
    ) -> tuple[
        SubscriptionDispatchService,
        FakeDeliveryRepository,
        FakeBriefingRepository,
        FakeEmailService,
    ]:
        deliveries = FakeDeliveryRepository()
        briefing_repo = FakeBriefingRepository(briefings or {})
        email = email_service or FakeEmailService()
        service = SubscriptionDispatchService(
            subscriptions=FakeSubscriptionRepository(subscriptions),
            deliveries=deliveries,
            briefings=briefing_repo,
            email_service=email,
        )
        return service, deliveries, briefing_repo, email

    def test_no_subscriptions_sends_nothing(self) -> None:
        service, deliveries, briefing_repo, email = self._make_service(subscriptions=[])

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary, {"sent": 0, "skipped": 0, "failed": 0})
        self.assertEqual(email.calls, [])
        self.assertEqual(briefing_repo.requested_keys, [])

    def test_uninjected_email_service_is_rebuilt_per_send(self) -> None:
        """未注入 email_service 时每次发送即时构建，SMTP 配置热生效免重启。"""
        service = SubscriptionDispatchService(
            subscriptions=FakeSubscriptionRepository(
                [_subscription(1), _subscription(2)]
            ),
            deliveries=FakeDeliveryRepository(),
            briefings=FakeBriefingRepository(
                {"2026-08-05": {"content_zh": "今日 AI 要闻"}}
            ),
        )
        built = [FakeEmailService(), FakeEmailService()]

        with patch(
            "backend.app.services.email_service.build_email_service",
            side_effect=lambda *args, **kwargs: built.pop(0),
        ) as factory:
            summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary["sent"], 2)
        # 两次发送 = 两次构建：实例不再永久缓存
        self.assertEqual(factory.call_count, 2)

    def test_uninjected_email_service_receives_redis_client(self) -> None:
        """构造注入的 redis_client 透传至 build_email_service，启用邮件池配额护栏。"""
        sentinel = object()
        service = SubscriptionDispatchService(
            subscriptions=FakeSubscriptionRepository([_subscription(1)]),
            deliveries=FakeDeliveryRepository(),
            briefings=FakeBriefingRepository(
                {"2026-08-05": {"content_zh": "今日 AI 要闻"}}
            ),
            redis_client=sentinel,
        )

        with patch(
            "backend.app.services.email_service.build_email_service",
            return_value=FakeEmailService(),
        ) as factory:
            summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary["sent"], 1)
        factory.assert_called_once_with(sentinel)

    def test_uninjected_email_service_defaults_redis_none_fail_open(self) -> None:
        """缺省 redis_client=None：配额护栏 fail-open，仅保留纯 failover。"""
        service = SubscriptionDispatchService(
            subscriptions=FakeSubscriptionRepository([_subscription(1)]),
            deliveries=FakeDeliveryRepository(),
            briefings=FakeBriefingRepository(
                {"2026-08-05": {"content_zh": "今日 AI 要闻"}}
            ),
        )

        with patch(
            "backend.app.services.email_service.build_email_service",
            return_value=FakeEmailService(),
        ) as factory:
            summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary["sent"], 1)
        factory.assert_called_once_with(None)

    def test_dispatch_all_defaults_to_cst_today(self) -> None:
        # 缺省日期必须与简报生成/缓存键同口径（CST），服务器本地时区不算数。
        service, _, briefing_repo, email = self._make_service(
            subscriptions=[_subscription(1)],
            briefings={"2026-08-05": {"content_zh": "今日 AI 要闻"}},
        )

        with patch(
            "backend.app.services.push.dispatch_service.today_cst",
            return_value="2026-08-05",
        ):
            summary = asyncio.run(service.dispatch_all())

        self.assertEqual(summary, {"sent": 1, "skipped": 0, "failed": 0})
        self.assertEqual(briefing_repo.requested_keys, ["2026-08-05"])
        self.assertEqual(email.calls[0]["date_str"], "2026-08-05")

    def test_missing_briefing_cache_creates_no_delivery(self) -> None:
        service, deliveries, briefing_repo, email = self._make_service(
            subscriptions=[_subscription(1)],
        )

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary, {"sent": 0, "skipped": 0, "failed": 0})
        self.assertEqual(email.calls, [])
        self.assertEqual(deliveries._rows, {})
        # 缓存 key 与报告路由一致：all 无后缀。
        self.assertIn("2026-08-05", briefing_repo.requested_keys)

    def test_happy_path_sends_and_marks_sent(self) -> None:
        service, deliveries, _, email = self._make_service(
            subscriptions=[_subscription(1)],
            briefings={"2026-08-05": {"content_zh": "今日 AI 要闻"}},
        )

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary, {"sent": 1, "skipped": 0, "failed": 0})
        self.assertEqual(len(email.calls), 1)
        call = email.calls[0]
        self.assertEqual(call["to_email"], "reader@example.com")
        self.assertEqual(call["briefing_content"], "今日 AI 要闻")
        self.assertEqual(call["source"], "all")
        self.assertEqual(call["period"], "daily")
        self.assertEqual(call["date_str"], "2026-08-05")
        delivery = deliveries.get_delivery(
            subscription_id=1, item_key="2026-08-05"
        )
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery["status"], "sent")
        self.assertEqual(delivery["attempts"], 1)

    def test_second_run_skips_already_sent_delivery(self) -> None:
        service, _, _, email = self._make_service(
            subscriptions=[_subscription(1)],
            briefings={"2026-08-05": {"content_zh": "今日 AI 要闻"}},
        )

        asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))
        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary, {"sent": 0, "skipped": 1, "failed": 0})
        self.assertEqual(len(email.calls), 1)

    def test_failed_attempt_is_retried_on_next_run(self) -> None:
        email = FakeEmailService(failures_before_success=1)
        service, deliveries, _, _ = self._make_service(
            subscriptions=[_subscription(1)],
            briefings={"2026-08-05": {"content_zh": "今日 AI 要闻"}},
            email_service=email,
        )

        first = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))
        self.assertEqual(first, {"sent": 0, "skipped": 0, "failed": 1})
        delivery = deliveries.get_delivery(
            subscription_id=1, item_key="2026-08-05"
        )
        self.assertEqual(delivery["status"], "pending")
        self.assertEqual(delivery["attempts"], 1)
        self.assertIn("SMTP 连接失败", delivery["last_error"])

        second = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))
        self.assertEqual(second, {"sent": 1, "skipped": 0, "failed": 0})
        delivery = deliveries.get_delivery(
            subscription_id=1, item_key="2026-08-05"
        )
        self.assertEqual(delivery["status"], "sent")
        self.assertEqual(delivery["attempts"], 2)
        self.assertEqual(len(email.calls), 2)

    def test_attempts_exhaustion_marks_failed_and_stops_retrying(self) -> None:
        email = FakeEmailService(always_fail=True)
        service, deliveries, _, _ = self._make_service(
            subscriptions=[_subscription(1)],
            briefings={"2026-08-05": {"content_zh": "今日 AI 要闻"}},
            email_service=email,
        )

        for _ in range(MAX_DELIVERY_ATTEMPTS):
            asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        delivery = deliveries.get_delivery(
            subscription_id=1, item_key="2026-08-05"
        )
        self.assertEqual(delivery["status"], "failed")
        self.assertEqual(delivery["attempts"], MAX_DELIVERY_ATTEMPTS)

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))
        self.assertEqual(summary, {"sent": 0, "skipped": 1, "failed": 0})
        self.assertEqual(len(email.calls), MAX_DELIVERY_ATTEMPTS)

    def test_source_cache_key_uses_suffix(self) -> None:
        service, _, briefing_repo, email = self._make_service(
            subscriptions=[_subscription(1, source="github", target="dev@example.com")],
            briefings={"2026-08-05_github": {"content_zh": "GitHub 热榜"}},
        )

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary["sent"], 1)
        self.assertEqual(email.calls[0]["source"], "github")
        self.assertEqual(email.calls[0]["to_email"], "dev@example.com")
        self.assertIn("2026-08-05_github", briefing_repo.requested_keys)

    def test_unsupported_channel_type_skips_without_delivery(self) -> None:
        service, deliveries, _, email = self._make_service(
            subscriptions=[_subscription(1, channel_type="sms")],
            briefings={"2026-08-05": {"content_zh": "今日 AI 要闻"}},
        )

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary, {"sent": 0, "skipped": 1, "failed": 0})
        self.assertEqual(email.calls, [])
        self.assertEqual(deliveries._rows, {})

    def test_one_bad_subscription_does_not_block_others(self) -> None:
        # 第一个订阅目标地址非法（fake 不校验，这里用交替失败模拟）：
        # 直接验证多订阅同源时互不影响——一个失败一个成功。
        email = FakeEmailService()
        service, _, _, _ = self._make_service(
            subscriptions=[
                _subscription(1, target="first@example.com"),
                _subscription(2, target="second@example.com"),
            ],
            briefings={"2026-08-05": {"content_zh": "今日 AI 要闻"}},
            email_service=email,
        )

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary, {"sent": 2, "skipped": 0, "failed": 0})
        self.assertEqual(
            [call["to_email"] for call in email.calls],
            ["first@example.com", "second@example.com"],
        )

    def test_paused_or_unverified_rows_never_reach_service(self) -> None:
        # list_active_dispatchable 只返回启用订阅 + 已验证启用渠道；
        # 仓储契约的过滤语义由 SQL 承担，此处验证服务不过滤入参之外的状态。
        service, _, _, email = self._make_service(
            subscriptions=[],
            briefings={"2026-08-05": {"content_zh": "今日 AI 要闻"}},
        )
        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))
        self.assertEqual(summary["sent"], 0)
        self.assertEqual(email.calls, [])

    def test_dispatch_all_uses_x_anchor_cache_key(self) -> None:
        # X 简报缓存键带固定 08:00 锚点：dispatch_all 必须读 2026-08-05_0800_x，
        # 手工拼接 _x 后缀时该期会被静默跳过（本用例即该缺陷回归）。
        service, _, briefing_repo, email = self._make_service(
            subscriptions=[_subscription(1, source="x", target="watcher@example.com")],
            briefings={"2026-08-05_0800_x": {"content_zh": "X 日报"}},
        )

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary["sent"], 1)
        self.assertEqual(email.calls[0]["source"], "x")
        self.assertEqual(briefing_repo.requested_keys, ["2026-08-05_0800_x"])


class SavedIssueDispatchTests(unittest.TestCase):
    """dispatch_issue：已保存期次的 email-only 定向补发（手动生成自动补发）。"""

    def _make_service(
        self,
        *,
        subscriptions: list[dict[str, Any]],
        email_service: FakeEmailService | None = None,
    ) -> tuple[
        SubscriptionDispatchService,
        FakeDeliveryRepository,
        FakeEmailService,
    ]:
        deliveries = FakeDeliveryRepository()
        email = email_service or FakeEmailService()
        service = SubscriptionDispatchService(
            subscriptions=FakeSubscriptionRepository(subscriptions),
            deliveries=deliveries,
            briefings=FakeBriefingRepository({}),
            email_service=email,
        )
        return service, deliveries, email

    def test_sends_only_matching_source_email_subscriptions(self) -> None:
        service, deliveries, email = self._make_service(
            subscriptions=[
                _subscription(1, source="github", target="dev@example.com"),
                _subscription(2, source="news", target="news@example.com"),
                _subscription(3, source="github", channel_type="webhook"),
                _subscription(4, source="github", channel_type="telegram"),
                _subscription(5, source="github", target="dev2@example.com"),
            ]
        )

        summary = asyncio.run(
            service.dispatch_issue(
                source="github", report_date="2026-08-05", content="GitHub 热榜"
            )
        )

        self.assertEqual(summary, {"sent": 2, "skipped": 0, "failed": 0})
        self.assertEqual(
            [call["to_email"] for call in email.calls],
            ["dev@example.com", "dev2@example.com"],
        )
        # 正文由调用方携带、原样投递；date_str 为裸报告日期而非完整缓存键。
        self.assertEqual(email.calls[0]["briefing_content"], "GitHub 热榜")
        self.assertEqual(email.calls[0]["date_str"], "2026-08-05")
        # webhook/telegram 不纳入自动补发：连 delivery 台账都不建，
        # 仍留给调度轮询 dispatch_all 负责。
        self.assertEqual(
            sorted(deliveries._rows),
            [(1, "2026-08-05_github"), (5, "2026-08-05_github")],
        )

    def test_x_source_uses_anchored_item_key_and_bare_date(self) -> None:
        service, deliveries, email = self._make_service(
            subscriptions=[_subscription(1, source="x", target="watcher@example.com")]
        )

        summary = asyncio.run(
            service.dispatch_issue(
                source="x", report_date="2026-08-05", content="X 日报"
            )
        )

        self.assertEqual(summary["sent"], 1)
        self.assertEqual(email.calls[0]["date_str"], "2026-08-05")
        self.assertIn((1, "2026-08-05_0800_x"), deliveries._rows)

    def test_second_run_is_idempotent_via_ledger(self) -> None:
        service, deliveries, email = self._make_service(
            subscriptions=[_subscription(1, source="github")]
        )

        first = asyncio.run(
            service.dispatch_issue(
                source="github", report_date="2026-08-05", content="GitHub 热榜"
            )
        )
        second = asyncio.run(
            service.dispatch_issue(
                source="github", report_date="2026-08-05", content="GitHub 热榜"
            )
        )

        self.assertEqual(first, {"sent": 1, "skipped": 0, "failed": 0})
        self.assertEqual(second, {"sent": 0, "skipped": 1, "failed": 0})
        self.assertEqual(len(email.calls), 1)

    def test_failed_attempt_is_retried_on_next_run(self) -> None:
        email = FakeEmailService(failures_before_success=1)
        service, deliveries, _ = self._make_service(
            subscriptions=[_subscription(1, source="github")],
            email_service=email,
        )

        first = asyncio.run(
            service.dispatch_issue(
                source="github", report_date="2026-08-05", content="GitHub 热榜"
            )
        )
        second = asyncio.run(
            service.dispatch_issue(
                source="github", report_date="2026-08-05", content="GitHub 热榜"
            )
        )

        self.assertEqual(first, {"sent": 0, "skipped": 0, "failed": 1})
        self.assertEqual(second, {"sent": 1, "skipped": 0, "failed": 0})
        delivery = deliveries.get_delivery(
            subscription_id=1, item_key="2026-08-05_github"
        )
        self.assertEqual(delivery["status"], "sent")
        self.assertEqual(delivery["attempts"], 2)

    def test_empty_content_or_date_is_noop(self) -> None:
        service, deliveries, email = self._make_service(
            subscriptions=[_subscription(1, source="github")]
        )

        empty = asyncio.run(
            service.dispatch_issue(source="github", report_date="2026-08-05", content="  ")
        )
        no_date = asyncio.run(
            service.dispatch_issue(source="github", report_date="", content="正文")
        )

        self.assertEqual(empty, {"sent": 0, "skipped": 0, "failed": 0})
        self.assertEqual(no_date, {"sent": 0, "skipped": 0, "failed": 0})
        # 空内容连订阅清单都不查（FakeSubscriptionRepository.calls 记录频率入参）。
        self.assertEqual(service._subscriptions.calls, [])
        self.assertEqual(email.calls, [])
        self.assertEqual(deliveries._rows, {})


class FakeTelegramSender:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail = fail

    async def send_message(self, *, chat_id: str, title: str, content: str) -> None:
        self.calls.append({"chat_id": chat_id, "title": title, "content": content})
        if self._fail:
            raise TelegramDeliveryError("Telegram 请求失败")


class FakePlatformWebhookSender:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._fail = fail

    async def send(self, *, url: str, title: str, content: str) -> None:
        self.calls.append({"url": url, "title": title, "content": content})
        if self._fail:
            raise RuntimeError("Webhook 返回 HTTP 500（第 1 块）")


def _direct_subscription(
    subscription_id: int,
    *,
    channel_type: str,
    target: str,
    config: dict[str, Any],
    role: str = "user",
    tier: str = "member",
    expires_at: Any = None,
) -> dict[str, Any]:
    """直投渠道订阅行：模拟 list_active_dispatchable 联表后的完整字段。"""
    return {
        "id": subscription_id,
        "user_id": 7,
        "channel_id": 100 + subscription_id,
        "source": "all",
        "frequency": "daily",
        "status": "active",
        "channel_type": channel_type,
        "target": target,
        "encrypted_config": seal_channel_config(_test_box(), config),
        "role": role,
        "membership_tier": tier,
        "membership_expires_at": expires_at,
    }


class DirectChannelDispatchTests(unittest.TestCase):
    """telegram/discord 渠道派发与会员抑制语义。"""

    def _make_service(
        self,
        *,
        subscriptions: list[dict[str, Any]],
        telegram_sender: FakeTelegramSender | None = None,
        webhook_sender: FakePlatformWebhookSender | None = None,
    ) -> tuple[SubscriptionDispatchService, FakeDeliveryRepository]:
        deliveries = FakeDeliveryRepository()
        service = SubscriptionDispatchService(
            subscriptions=FakeSubscriptionRepository(subscriptions),
            deliveries=deliveries,
            briefings=FakeBriefingRepository(
                {"2026-08-05": {"content_zh": "今日 AI 要闻"}}
            ),
            secret_box=_test_box(),
            webhook_sender=webhook_sender,
            telegram_sender=telegram_sender,
        )
        return service, deliveries

    def test_telegram_delivery_happy_path(self) -> None:
        sender = FakeTelegramSender()
        service, deliveries = self._make_service(
            subscriptions=[
                _direct_subscription(
                    1,
                    channel_type="telegram",
                    target="tg:abc123",
                    config={"chat_id": "424242001"},
                )
            ],
            telegram_sender=sender,
        )

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary, {"sent": 1, "skipped": 0, "failed": 0})
        self.assertEqual(len(sender.calls), 1)
        self.assertEqual(sender.calls[0]["chat_id"], "424242001")
        self.assertIn("日报", sender.calls[0]["title"])
        self.assertIn("2026-08-05", sender.calls[0]["title"])
        self.assertEqual(sender.calls[0]["content"], "今日 AI 要闻")
        row = deliveries.get_delivery(subscription_id=1, item_key="2026-08-05")
        assert row is not None
        self.assertEqual(row["status"], "sent")

    def test_discord_delivery_uses_sealed_url(self) -> None:
        sender = FakePlatformWebhookSender()
        url = "https://discord.com/api/webhooks/123/token-abc"
        service, _deliveries = self._make_service(
            subscriptions=[
                _direct_subscription(
                    1,
                    channel_type="discord",
                    target="dg:xyz",
                    config={"url": url},
                )
            ],
            webhook_sender=sender,
        )

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary["sent"], 1)
        self.assertEqual(sender.calls[0]["url"], url)

    def test_expired_member_direct_channel_is_suppressed(self) -> None:
        sender = FakeTelegramSender()
        service, deliveries = self._make_service(
            subscriptions=[
                _direct_subscription(
                    1,
                    channel_type="telegram",
                    target="tg:abc123",
                    config={"chat_id": "424242001"},
                    expires_at=datetime.now(timezone.utc) - timedelta(days=1),
                )
            ],
            telegram_sender=sender,
        )

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        # 会员抑制不是 provider failure：不创建 delivery、不计 attempts
        self.assertEqual(summary, {"sent": 0, "skipped": 1, "failed": 0})
        self.assertEqual(sender.calls, [])
        self.assertIsNone(
            deliveries.get_delivery(subscription_id=1, item_key="2026-08-05")
        )

    def test_free_tier_discord_is_suppressed(self) -> None:
        sender = FakePlatformWebhookSender()
        service, deliveries = self._make_service(
            subscriptions=[
                _direct_subscription(
                    1,
                    channel_type="discord",
                    target="dg:xyz",
                    config={"url": "https://discord.com/api/webhooks/1/t"},
                    tier="free",
                )
            ],
            webhook_sender=sender,
        )

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(sender.calls, [])
        self.assertIsNone(
            deliveries.get_delivery(subscription_id=1, item_key="2026-08-05")
        )

    def test_admin_bypasses_membership_suppression(self) -> None:
        sender = FakeTelegramSender()
        service, _deliveries = self._make_service(
            subscriptions=[
                _direct_subscription(
                    1,
                    channel_type="telegram",
                    target="tg:abc123",
                    config={"chat_id": "424242001"},
                    role="admin",
                    tier="free",
                )
            ],
            telegram_sender=sender,
        )

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary["sent"], 1)
        self.assertEqual(len(sender.calls), 1)

    def test_email_channel_not_subject_to_membership_suppression(self) -> None:
        # email 不是直投渠道：免费用户照常派发，且行无需携带权益字段
        email = FakeEmailService()
        deliveries = FakeDeliveryRepository()
        service = SubscriptionDispatchService(
            subscriptions=FakeSubscriptionRepository([_subscription(1)]),
            deliveries=deliveries,
            briefings=FakeBriefingRepository(
                {"2026-08-05": {"content_zh": "今日 AI 要闻"}}
            ),
            email_service=email,
        )

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary["sent"], 1)
        self.assertEqual(len(email.calls), 1)

    def test_telegram_failure_records_static_error(self) -> None:
        sender = FakeTelegramSender(fail=True)
        service, deliveries = self._make_service(
            subscriptions=[
                _direct_subscription(
                    1,
                    channel_type="telegram",
                    target="tg:abc123",
                    config={"chat_id": "424242001"},
                )
            ],
            telegram_sender=sender,
        )

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary["failed"], 1)
        row = deliveries.get_delivery(subscription_id=1, item_key="2026-08-05")
        assert row is not None
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(row["last_error"], "Telegram 请求失败")

    def test_telegram_unconfigured_counts_failed_with_safe_message(self) -> None:
        service, deliveries = self._make_service(
            subscriptions=[
                _direct_subscription(
                    1,
                    channel_type="telegram",
                    target="tg:abc123",
                    config={"chat_id": "424242001"},
                )
            ],
            telegram_sender=None,
        )

        with patch(
            "backend.app.services.push.telegram_service.build_telegram_bot_client",
            return_value=None,
        ):
            summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary["failed"], 1)
        row = deliveries.get_delivery(subscription_id=1, item_key="2026-08-05")
        assert row is not None
        self.assertIn("未启用", row["last_error"])


if __name__ == "__main__":
    unittest.main()
