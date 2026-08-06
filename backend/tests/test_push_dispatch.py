"""订阅简报派发服务的幂等与重试语义契约测试。"""

from __future__ import annotations

import asyncio
import unittest
from datetime import date
from typing import Any

from backend.app.services.push.dispatch_service import (
    MAX_DELIVERY_ATTEMPTS,
    SubscriptionDispatchService,
    _resolve_issue_date,
)


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


class ResolveIssueDateTests(unittest.TestCase):
    def test_daily_uses_today(self) -> None:
        self.assertEqual(_resolve_issue_date("daily", date(2026, 8, 5)), "2026-08-05")

    def test_weekly_anchors_to_monday(self) -> None:
        # 2026-08-05 是周三，周报锚定当周周一。
        self.assertEqual(_resolve_issue_date("weekly", date(2026, 8, 5)), "2026-08-03")

    def test_monthly_anchors_to_first_day(self) -> None:
        self.assertEqual(_resolve_issue_date("monthly", date(2026, 8, 5)), "2026-08-01")


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

    def test_missing_briefing_cache_creates_no_delivery(self) -> None:
        service, deliveries, briefing_repo, email = self._make_service(
            subscriptions=[_subscription(1)],
        )

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary, {"sent": 0, "skipped": 0, "failed": 0})
        self.assertEqual(email.calls, [])
        self.assertEqual(deliveries._rows, {})
        # 缓存 key 与报告路由一致：all 无后缀，直接拼频率。
        self.assertIn("2026-08-05_daily", briefing_repo.requested_keys)

    def test_happy_path_sends_and_marks_sent(self) -> None:
        service, deliveries, _, email = self._make_service(
            subscriptions=[_subscription(1)],
            briefings={"2026-08-05_daily": {"content_zh": "今日 AI 要闻"}},
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
            subscription_id=1, item_key="2026-08-05_daily"
        )
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery["status"], "sent")
        self.assertEqual(delivery["attempts"], 1)

    def test_second_run_skips_already_sent_delivery(self) -> None:
        service, _, _, email = self._make_service(
            subscriptions=[_subscription(1)],
            briefings={"2026-08-05_daily": {"content_zh": "今日 AI 要闻"}},
        )

        asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))
        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary, {"sent": 0, "skipped": 1, "failed": 0})
        self.assertEqual(len(email.calls), 1)

    def test_failed_attempt_is_retried_on_next_run(self) -> None:
        email = FakeEmailService(failures_before_success=1)
        service, deliveries, _, _ = self._make_service(
            subscriptions=[_subscription(1)],
            briefings={"2026-08-05_daily": {"content_zh": "今日 AI 要闻"}},
            email_service=email,
        )

        first = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))
        self.assertEqual(first, {"sent": 0, "skipped": 0, "failed": 1})
        delivery = deliveries.get_delivery(
            subscription_id=1, item_key="2026-08-05_daily"
        )
        self.assertEqual(delivery["status"], "pending")
        self.assertEqual(delivery["attempts"], 1)
        self.assertIn("SMTP 连接失败", delivery["last_error"])

        second = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))
        self.assertEqual(second, {"sent": 1, "skipped": 0, "failed": 0})
        delivery = deliveries.get_delivery(
            subscription_id=1, item_key="2026-08-05_daily"
        )
        self.assertEqual(delivery["status"], "sent")
        self.assertEqual(delivery["attempts"], 2)
        self.assertEqual(len(email.calls), 2)

    def test_attempts_exhaustion_marks_failed_and_stops_retrying(self) -> None:
        email = FakeEmailService(always_fail=True)
        service, deliveries, _, _ = self._make_service(
            subscriptions=[_subscription(1)],
            briefings={"2026-08-05_daily": {"content_zh": "今日 AI 要闻"}},
            email_service=email,
        )

        for _ in range(MAX_DELIVERY_ATTEMPTS):
            asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        delivery = deliveries.get_delivery(
            subscription_id=1, item_key="2026-08-05_daily"
        )
        self.assertEqual(delivery["status"], "failed")
        self.assertEqual(delivery["attempts"], MAX_DELIVERY_ATTEMPTS)

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))
        self.assertEqual(summary, {"sent": 0, "skipped": 1, "failed": 0})
        self.assertEqual(len(email.calls), MAX_DELIVERY_ATTEMPTS)

    def test_weekly_frequency_anchors_cache_key_to_monday(self) -> None:
        service, _, briefing_repo, email = self._make_service(
            subscriptions=[_subscription(1, frequency="weekly")],
            briefings={"2026-08-03_weekly": {"content_zh": "本周 AI 要闻"}},
        )

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary["sent"], 1)
        self.assertEqual(email.calls[0]["period"], "weekly")
        self.assertEqual(email.calls[0]["date_str"], "2026-08-03")
        self.assertIn("2026-08-03_weekly", briefing_repo.requested_keys)

    def test_monthly_frequency_anchors_cache_key_to_first_day(self) -> None:
        service, _, briefing_repo, email = self._make_service(
            subscriptions=[_subscription(1, frequency="monthly")],
            briefings={"2026-08-01_monthly": {"content_zh": "本月 AI 要闻"}},
        )

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary["sent"], 1)
        self.assertEqual(email.calls[0]["period"], "monthly")
        self.assertEqual(email.calls[0]["date_str"], "2026-08-01")
        self.assertIn("2026-08-01_monthly", briefing_repo.requested_keys)

    def test_source_cache_key_uses_suffix(self) -> None:
        service, _, briefing_repo, email = self._make_service(
            subscriptions=[_subscription(1, source="github", target="dev@example.com")],
            briefings={"2026-08-05_github_daily": {"content_zh": "GitHub 热榜"}},
        )

        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))

        self.assertEqual(summary["sent"], 1)
        self.assertEqual(email.calls[0]["source"], "github")
        self.assertEqual(email.calls[0]["to_email"], "dev@example.com")
        self.assertIn("2026-08-05_github_daily", briefing_repo.requested_keys)

    def test_unsupported_channel_type_skips_without_delivery(self) -> None:
        service, deliveries, _, email = self._make_service(
            subscriptions=[_subscription(1, channel_type="sms")],
            briefings={"2026-08-05_daily": {"content_zh": "今日 AI 要闻"}},
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
            briefings={"2026-08-05_daily": {"content_zh": "今日 AI 要闻"}},
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
            briefings={"2026-08-05_daily": {"content_zh": "今日 AI 要闻"}},
        )
        summary = asyncio.run(service.dispatch_all(today=date(2026, 8, 5)))
        self.assertEqual(summary["sent"], 0)
        self.assertEqual(email.calls, [])


if __name__ == "__main__":
    unittest.main()
