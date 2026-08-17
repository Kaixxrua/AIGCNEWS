"""简报订阅档位配额单元测试：跨体系合计、存量豁免（grandfather）与免费档上限。"""

from __future__ import annotations

import unittest

from backend.app.services.membership.subscription_quota import (
    FREE_TIER_DAILY_SUBSCRIPTION_LIMIT,
    SUBSCRIPTION_QUOTA_EXCEEDED_DETAIL,
    SubscriptionQuotaExceededError,
    collect_active_daily_sources,
    ensure_subscription_quota,
)


class _BriefingRows:
    """体系 A 读边界：get_user_briefing_subscriptions 只回活跃日报行。"""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def get_user_briefing_subscriptions(self, user_id: int) -> list[dict]:
        return [row for row in self._rows if row["user_id"] == user_id]


class _UserSubscriptionRows:
    """体系 B 读边界：list_subscriptions 回全部行（含 paused）。"""

    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def list_subscriptions(self, user_id: int) -> list[dict]:
        return [row for row in self._rows if row["user_id"] == user_id]


def _collect(
    briefing_rows: list[dict] | None = None,
    user_sub_rows: list[dict] | None = None,
    user_id: int = 7,
) -> set[str]:
    return collect_active_daily_sources(
        briefing_subscriptions=_BriefingRows(briefing_rows or []),
        user_subscriptions=_UserSubscriptionRows(user_sub_rows or []),
        user_id=user_id,
    )


class CollectActiveDailySourcesTests(unittest.TestCase):
    def test_cross_system_sources_are_deduplicated(self) -> None:
        sources = _collect(
            briefing_rows=[{"user_id": 7, "source": "github"}],
            user_sub_rows=[
                {"user_id": 7, "source": "github", "status": "active"},
                {"user_id": 7, "source": "news", "status": "active"},
            ],
        )
        self.assertEqual(sources, {"github", "news"})

    def test_paused_user_subscriptions_are_excluded(self) -> None:
        sources = _collect(
            user_sub_rows=[
                {"user_id": 7, "source": "github", "status": "paused"},
                {"user_id": 7, "source": "news", "status": "active"},
            ],
        )
        self.assertEqual(sources, {"news"})

    def test_missing_frequency_defaults_to_daily_and_non_daily_excluded(self) -> None:
        sources = _collect(
            user_sub_rows=[
                {"user_id": 7, "source": "github", "status": "active"},
                {
                    "user_id": 7,
                    "source": "news",
                    "status": "active",
                    "frequency": "daily",
                },
                {
                    "user_id": 7,
                    "source": "x",
                    "status": "active",
                    "frequency": "weekly",
                },
            ],
        )
        self.assertEqual(sources, {"github", "news"})

    def test_rows_without_source_are_excluded(self) -> None:
        sources = _collect(
            briefing_rows=[{"user_id": 7, "source": ""}],
            user_sub_rows=[{"user_id": 7, "status": "active"}],
        )
        self.assertEqual(sources, set())

    def test_other_users_rows_are_excluded(self) -> None:
        sources = _collect(
            briefing_rows=[{"user_id": 8, "source": "github"}],
            user_sub_rows=[{"user_id": 8, "source": "news", "status": "active"}],
        )
        self.assertEqual(sources, set())


class EnsureSubscriptionQuotaTests(unittest.TestCase):
    def test_free_tier_limit_is_one_module(self) -> None:
        self.assertEqual(FREE_TIER_DAILY_SUBSCRIPTION_LIMIT, 1)

    def test_member_tier_always_allowed(self) -> None:
        ensure_subscription_quota(
            tier="member",
            active_sources={"github", "news", "x"},
            adding_sources={"arxiv", "producthunt"},
        )

    def test_unknown_tier_falls_back_to_free(self) -> None:
        with self.assertRaises(SubscriptionQuotaExceededError):
            ensure_subscription_quota(
                tier="vip",
                active_sources={"github"},
                adding_sources={"news"},
            )

    def test_free_tier_first_module_allowed(self) -> None:
        ensure_subscription_quota(
            tier="free",
            active_sources=set(),
            adding_sources={"github"},
        )

    def test_free_tier_second_module_rejected(self) -> None:
        with self.assertRaises(SubscriptionQuotaExceededError) as ctx:
            ensure_subscription_quota(
                tier="free",
                active_sources={"github"},
                adding_sources={"news"},
            )
        self.assertEqual(ctx.exception.detail, SUBSCRIPTION_QUOTA_EXCEEDED_DETAIL)
        self.assertIn("开通会员", ctx.exception.detail)

    def test_free_tier_batch_beyond_limit_rejected(self) -> None:
        with self.assertRaises(SubscriptionQuotaExceededError):
            ensure_subscription_quota(
                tier="free",
                active_sources=set(),
                adding_sources={"github", "news"},
            )

    def test_grandfathered_overquota_keeps_existing_but_rejects_new(self) -> None:
        # 存量超档（历史上订了 3 个）：不追缴，但任何新模块都拒绝
        with self.assertRaises(SubscriptionQuotaExceededError):
            ensure_subscription_quota(
                tier="free",
                active_sources={"github", "news", "x"},
                adding_sources={"arxiv"},
            )

    def test_grandfathered_repeat_upsert_is_idempotent(self) -> None:
        # 对已活跃 source 的重复 upsert 幂等放行（不属于新增模块）
        ensure_subscription_quota(
            tier="free",
            active_sources={"github", "news", "x"},
            adding_sources={"github"},
        )

    def test_empty_adding_is_always_allowed(self) -> None:
        ensure_subscription_quota(
            tier="free",
            active_sources={"github"},
            adding_sources=set(),
        )


if __name__ == "__main__":
    unittest.main()
