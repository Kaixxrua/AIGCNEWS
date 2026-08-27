from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest

from backend.app.services.membership.subscription_quota import (
    SubscriptionQuotaExceededError,
)
from backend.app.services.push.channel_service import CHANNEL_STATUS_ACTIVE
from backend.app.services.push.errors import (
    PushChannelDisabledError,
    PushChannelNotFoundError,
    PushChannelNotVerifiedError,
    VipRequiredError,
)
from backend.app.services.report.subscription_plan_service import (
    DeliveryTarget,
    InvalidSubscriptionPlanError,
    ReportSubscriptionPlanService,
)


class FakeTransactionDatabase:
    """提供可断言的 transaction 上下文，但不连接真实数据库。"""

    def __init__(self) -> None:
        self.connections: list[object] = []

    @contextmanager
    def transaction(self, *, acquisition_timeout: float | None = None) -> Iterator[object]:
        conn = object()
        self.connections.append(conn)
        try:
            yield conn
        finally:
            pass


def _service(
    *,
    briefing_subscriptions: Any | None = None,
    user_subscriptions: Any | None = None,
    push_channels: Any | None = None,
) -> ReportSubscriptionPlanService:
    return ReportSubscriptionPlanService(
        database=FakeTransactionDatabase(),
        briefing_subscriptions=briefing_subscriptions or MagicMock(),
        user_subscriptions=user_subscriptions or MagicMock(),
        push_channels=push_channels or MagicMock(),
    )


class TestReportSubscriptionPlanServiceGetPlan:
    def test_free_user_cannot_select_multiple_sources(self) -> None:
        service = _service()
        plan = service.get_plan(user={"user_id": 1, "email": "a@b.com", "membership_tier": "free"}, user_id=1)

        assert plan["can_select_multiple_sources"] is False
        assert plan["max_sources"] == 1

    def test_member_can_select_multiple_sources(self) -> None:
        service = _service()
        plan = service.get_plan(
            user={"user_id": 1, "email": "a@b.com", "membership_tier": "member"},
            user_id=1,
        )

        assert plan["can_select_multiple_sources"] is True
        assert plan["max_sources"] == 8

    def test_admin_can_select_multiple_sources(self) -> None:
        service = _service()
        plan = service.get_plan(
            user={"user_id": 1, "email": "a@b.com", "role": "admin"},
            user_id=1,
        )

        assert plan["can_select_multiple_sources"] is True

    def test_expired_member_treated_as_free(self) -> None:
        service = _service()
        plan = service.get_plan(
            user={
                "user_id": 1,
                "email": "a@b.com",
                "membership_tier": "member",
                "membership_expires_at": "2020-01-01T00:00:00",
            },
            user_id=1,
        )

        assert plan["can_select_multiple_sources"] is False
        assert plan["max_sources"] == 1

    def test_capabilities_include_rss_and_account_email(self) -> None:
        push_channels = MagicMock()
        push_channels.list_channels.return_value = []
        service = _service(push_channels=push_channels)

        plan = service.get_plan(user={"user_id": 1, "email": "a@b.com"}, user_id=1)

        kinds = {c["kind"] for c in plan["capabilities"]}
        assert "rss" in kinds
        assert "account_email" in kinds

    def test_capabilities_include_verified_push_channels(self) -> None:
        push_channels = MagicMock()
        push_channels.list_channels.return_value = [
            {
                "id": 10,
                "channel_type": "webhook",
                "target": "https://x.co",
                "verified": True,
                "status": CHANNEL_STATUS_ACTIVE,
            }
        ]
        service = _service(push_channels=push_channels)

        plan = service.get_plan(user={"user_id": 1, "email": "a@b.com"}, user_id=1)

        push_caps = [
            c
            for c in plan["capabilities"]
            if c["kind"] == "push_channel" and c.get("status") != "coming_soon"
        ]
        assert len(push_caps) == 1
        assert push_caps[0]["channel_id"] == 10
        assert push_caps[0]["channel_type"] == "webhook"
        assert push_caps[0]["target"] == "https://x.co"

    def test_unverified_push_channel_is_not_selectable(self) -> None:
        push_channels = MagicMock()
        push_channels.list_channels.return_value = [
            {
                "id": 11,
                "channel_type": "webhook",
                "target": "https://example.com/hook",
                "verified": False,
                "status": CHANNEL_STATUS_ACTIVE,
            }
        ]
        service = _service(push_channels=push_channels)

        plan = service.get_plan(user={"user_id": 1, "email": "a@b.com"}, user_id=1)

        push_caps = [
            c
            for c in plan["capabilities"]
            if c["kind"] == "push_channel" and c.get("status") != "coming_soon"
        ]
        assert len(push_caps) == 1
        assert push_caps[0]["selectable"] is False
        assert push_caps[0]["disabled_reason"] == "渠道尚未验证"

    def test_wechat_and_feishu_are_visible_but_disabled(self) -> None:
        push_channels = MagicMock()
        push_channels.list_channels.return_value = []
        service = _service(push_channels=push_channels)

        plan = service.get_plan(user={"user_id": 1, "email": "a@b.com"}, user_id=1)

        coming_soon = [
            c
            for c in plan["capabilities"]
            if c["kind"] == "push_channel" and c.get("status") == "coming_soon"
        ]
        types = {c["channel_type"] for c in coming_soon}
        assert types == {"feishu", "wechat"}
        assert all(c["selectable"] is False for c in coming_soon)
        assert all(c["disabled_reason"] == "暂未开放" for c in coming_soon)

    def test_active_sources_combines_briefing_and_push(self) -> None:
        briefing_subscriptions = MagicMock()
        briefing_subscriptions.get_user_briefing_subscriptions.return_value = [
            {"source": "github"}
        ]
        user_subscriptions = MagicMock()
        user_subscriptions.list_subscriptions.return_value = [
            {"source": "news", "channel_id": 1, "status": "active", "frequency": "daily"}
        ]
        push_channels = MagicMock()
        push_channels.list_channels.return_value = []
        service = _service(
            briefing_subscriptions=briefing_subscriptions,
            user_subscriptions=user_subscriptions,
            push_channels=push_channels,
        )

        plan = service.get_plan(user={"user_id": 1, "email": "a@b.com"}, user_id=1)

        assert set(plan["active_sources"]) == {"github", "news"}


class TestReportSubscriptionPlanServiceApplyPlan:
    def test_rejects_empty_sources(self) -> None:
        service = _service()

        with pytest.raises(InvalidSubscriptionPlanError):
            service.apply_plan(
                user={"user_id": 1, "email": "a@b.com"},
                user_id=1,
                email="a@b.com",
                sources=[],
                deliveries=[DeliveryTarget(kind="account_email")],
            )

    def test_rejects_invalid_sources(self) -> None:
        service = _service()

        with pytest.raises(InvalidSubscriptionPlanError):
            service.apply_plan(
                user={"user_id": 1, "email": "a@b.com"},
                user_id=1,
                email="a@b.com",
                sources=["invalid"],
                deliveries=[DeliveryTarget(kind="account_email")],
            )

    def test_rejects_empty_deliveries(self) -> None:
        service = _service()

        with pytest.raises(InvalidSubscriptionPlanError):
            service.apply_plan(
                user={"user_id": 1, "email": "a@b.com"},
                user_id=1,
                email="a@b.com",
                sources=["github"],
                deliveries=[],
            )

    def test_free_user_cannot_select_multiple_sources(self) -> None:
        service = _service()

        with pytest.raises(SubscriptionQuotaExceededError):
            service.apply_plan(
                user={"user_id": 1, "email": "a@b.com", "membership_tier": "free"},
                user_id=1,
                email="a@b.com",
                sources=["github", "news"],
                deliveries=[DeliveryTarget(kind="account_email")],
            )

    def test_member_can_select_multiple_sources(self) -> None:
        briefing_subscriptions = MagicMock()
        briefing_subscriptions.upsert_briefing_subscription.return_value = {"id": 1}
        service = _service(briefing_subscriptions=briefing_subscriptions)

        result = service.apply_plan(
            user={"user_id": 1, "email": "a@b.com", "membership_tier": "member"},
            user_id=1,
            email="a@b.com",
            sources=["github", "news"],
            deliveries=[DeliveryTarget(kind="account_email")],
        )

        assert set(result["sources"]) == {"github", "news"}
        assert result["deliveries"][0]["kind"] == "account_email"

    def test_account_email_upserts_briefing_subscriptions(self) -> None:
        briefing_subscriptions = MagicMock()
        briefing_subscriptions.upsert_briefing_subscription.return_value = {"id": 1}
        service = _service(briefing_subscriptions=briefing_subscriptions)

        result = service.apply_plan(
            user={"user_id": 1, "email": "a@b.com"},
            user_id=1,
            email="a@b.com",
            sources=["github"],
            deliveries=[DeliveryTarget(kind="account_email")],
        )

        briefing_subscriptions.upsert_briefing_subscription.assert_called_once_with(
            user_id=1, email="a@b.com", source="github", connection=service._database.connections[0]
        )
        assert result["deliveries"][0] == {
            "kind": "account_email",
            "channel_id": None,
            "feed": None,
            "status": "applied",
        }

    def test_rss_is_virtual_and_does_not_write_push(self) -> None:
        user_subscriptions = MagicMock()
        service = _service(user_subscriptions=user_subscriptions)

        result = service.apply_plan(
            user={"user_id": 1, "email": "a@b.com"},
            user_id=1,
            email="a@b.com",
            sources=["github"],
            deliveries=[DeliveryTarget(kind="rss", feed="briefing")],
        )

        user_subscriptions.create_subscription.assert_not_called()
        assert result["deliveries"][0] == {
            "kind": "rss",
            "channel_id": None,
            "feed": "briefing",
            "status": "applied",
        }

    def test_push_channel_creates_user_subscription(self) -> None:
        briefing_subscriptions = MagicMock()
        briefing_subscriptions.get_user_briefing_subscriptions.return_value = []
        user_subscriptions = MagicMock()
        user_subscriptions.list_subscriptions.return_value = []
        user_subscriptions.create_subscription.return_value = {"id": 2}
        push_channels = MagicMock()
        push_channels.list_channels.return_value = [
            {
                "id": 10,
                "channel_type": "webhook",
                "target": "https://example.com/hook",
                "verified": True,
                "status": CHANNEL_STATUS_ACTIVE,
            }
        ]
        service = _service(
            briefing_subscriptions=briefing_subscriptions,
            user_subscriptions=user_subscriptions,
            push_channels=push_channels,
        )

        result = service.apply_plan(
            user={"user_id": 1, "email": "a@b.com"},
            user_id=1,
            email="a@b.com",
            sources=["github"],
            deliveries=[DeliveryTarget(kind="push_channel", channel_id=10)],
        )

        user_subscriptions.create_subscription.assert_called_once_with(
            user_id=1,
            channel_id=10,
            source="github",
            frequency="daily",
            connection=service._database.connections[0],
        )
        assert result["deliveries"][0] == {
            "kind": "push_channel",
            "channel_id": 10,
            "feed": None,
            "status": "applied",
        }

    def test_push_channel_missing_raises_not_found(self) -> None:
        briefing_subscriptions = MagicMock()
        briefing_subscriptions.get_user_briefing_subscriptions.return_value = []
        user_subscriptions = MagicMock()
        user_subscriptions.list_subscriptions.return_value = []
        push_channels = MagicMock()
        push_channels.list_channels.return_value = []
        service = _service(
            briefing_subscriptions=briefing_subscriptions,
            user_subscriptions=user_subscriptions,
            push_channels=push_channels,
        )

        with pytest.raises(PushChannelNotFoundError):
            service.apply_plan(
                user={"user_id": 1, "email": "a@b.com"},
                user_id=1,
                email="a@b.com",
                sources=["github"],
                deliveries=[DeliveryTarget(kind="push_channel", channel_id=99)],
            )

    def test_push_channel_unverified_raises(self) -> None:
        briefing_subscriptions = MagicMock()
        briefing_subscriptions.get_user_briefing_subscriptions.return_value = []
        user_subscriptions = MagicMock()
        user_subscriptions.list_subscriptions.return_value = []
        push_channels = MagicMock()
        push_channels.list_channels.return_value = [
            {
                "id": 10,
                "channel_type": "webhook",
                "target": "https://example.com/hook",
                "verified": False,
                "status": CHANNEL_STATUS_ACTIVE,
            }
        ]
        service = _service(
            briefing_subscriptions=briefing_subscriptions,
            user_subscriptions=user_subscriptions,
            push_channels=push_channels,
        )

        with pytest.raises(PushChannelNotVerifiedError):
            service.apply_plan(
                user={"user_id": 1, "email": "a@b.com"},
                user_id=1,
                email="a@b.com",
                sources=["github"],
                deliveries=[DeliveryTarget(kind="push_channel", channel_id=10)],
            )

    def test_push_channel_disabled_raises(self) -> None:
        briefing_subscriptions = MagicMock()
        briefing_subscriptions.get_user_briefing_subscriptions.return_value = []
        user_subscriptions = MagicMock()
        user_subscriptions.list_subscriptions.return_value = []
        push_channels = MagicMock()
        push_channels.list_channels.return_value = [
            {
                "id": 10,
                "channel_type": "webhook",
                "target": "https://example.com/hook",
                "verified": True,
                "status": "disabled",
            }
        ]
        service = _service(
            briefing_subscriptions=briefing_subscriptions,
            user_subscriptions=user_subscriptions,
            push_channels=push_channels,
        )

        with pytest.raises(PushChannelDisabledError):
            service.apply_plan(
                user={"user_id": 1, "email": "a@b.com"},
                user_id=1,
                email="a@b.com",
                sources=["github"],
                deliveries=[DeliveryTarget(kind="push_channel", channel_id=10)],
            )

    def test_wechat_channel_rejected_even_if_exists(self) -> None:
        briefing_subscriptions = MagicMock()
        briefing_subscriptions.get_user_briefing_subscriptions.return_value = []
        user_subscriptions = MagicMock()
        user_subscriptions.list_subscriptions.return_value = []
        push_channels = MagicMock()
        push_channels.list_channels.return_value = [
            {
                "id": 10,
                "channel_type": "wechat",
                "target": "wxid",
                "verified": True,
                "status": CHANNEL_STATUS_ACTIVE,
            }
        ]
        service = _service(
            briefing_subscriptions=briefing_subscriptions,
            user_subscriptions=user_subscriptions,
            push_channels=push_channels,
        )

        with pytest.raises(InvalidSubscriptionPlanError):
            service.apply_plan(
                user={"user_id": 1, "email": "a@b.com"},
                user_id=1,
                email="a@b.com",
                sources=["github"],
                deliveries=[DeliveryTarget(kind="push_channel", channel_id=10)],
            )

    def test_discord_requires_member(self) -> None:
        briefing_subscriptions = MagicMock()
        briefing_subscriptions.get_user_briefing_subscriptions.return_value = []
        user_subscriptions = MagicMock()
        user_subscriptions.list_subscriptions.return_value = []
        push_channels = MagicMock()
        push_channels.list_channels.return_value = [
            {
                "id": 10,
                "channel_type": "discord",
                "target": "#channel",
                "verified": True,
                "status": CHANNEL_STATUS_ACTIVE,
            }
        ]
        service = _service(
            briefing_subscriptions=briefing_subscriptions,
            user_subscriptions=user_subscriptions,
            push_channels=push_channels,
        )

        with pytest.raises(VipRequiredError):
            service.apply_plan(
                user={"user_id": 1, "email": "a@b.com", "membership_tier": "free"},
                user_id=1,
                email="a@b.com",
                sources=["github"],
                deliveries=[DeliveryTarget(kind="push_channel", channel_id=10)],
            )

    def test_free_user_same_source_across_channels_is_exempt(self) -> None:
        briefing_subscriptions = MagicMock()
        briefing_subscriptions.get_user_briefing_subscriptions.return_value = [
            {"source": "github"}
        ]
        user_subscriptions = MagicMock()
        user_subscriptions.list_subscriptions.return_value = []
        push_channels = MagicMock()
        push_channels.list_channels.return_value = [
            {
                "id": 10,
                "channel_type": "webhook",
                "target": "https://example.com/hook",
                "verified": True,
                "status": CHANNEL_STATUS_ACTIVE,
            }
        ]
        service = _service(
            briefing_subscriptions=briefing_subscriptions,
            user_subscriptions=user_subscriptions,
            push_channels=push_channels,
        )

        result = service.apply_plan(
            user={"user_id": 1, "email": "a@b.com", "membership_tier": "free"},
            user_id=1,
            email="a@b.com",
            sources=["github"],
            deliveries=[DeliveryTarget(kind="push_channel", channel_id=10)],
        )

        assert result["sources"] == ["github"]

    def test_free_user_adding_second_source_exceeds_quota(self) -> None:
        briefing_subscriptions = MagicMock()
        briefing_subscriptions.get_user_briefing_subscriptions.return_value = [
            {"source": "github"}
        ]
        user_subscriptions = MagicMock()
        user_subscriptions.list_subscriptions.return_value = []
        push_channels = MagicMock()
        push_channels.list_channels.return_value = []
        service = _service(
            briefing_subscriptions=briefing_subscriptions,
            user_subscriptions=user_subscriptions,
            push_channels=push_channels,
        )

        with pytest.raises(SubscriptionQuotaExceededError):
            service.apply_plan(
                user={"user_id": 1, "email": "a@b.com", "membership_tier": "free"},
                user_id=1,
                email="a@b.com",
                sources=["news"],
                deliveries=[DeliveryTarget(kind="account_email")],
            )

    def test_duplicate_deliveries_are_normalized(self) -> None:
        briefing_subscriptions = MagicMock()
        briefing_subscriptions.upsert_briefing_subscription.return_value = {"id": 1}
        service = _service(briefing_subscriptions=briefing_subscriptions)

        result = service.apply_plan(
            user={"user_id": 1, "email": "a@b.com"},
            user_id=1,
            email="a@b.com",
            sources=["github"],
            deliveries=[
                DeliveryTarget(kind="account_email"),
                DeliveryTarget(kind="account_email"),
            ],
        )

        assert len(result["deliveries"]) == 1
        briefing_subscriptions.upsert_briefing_subscription.assert_called_once()

    def test_existing_push_subscription_is_skipped(self) -> None:
        briefing_subscriptions = MagicMock()
        briefing_subscriptions.get_user_briefing_subscriptions.return_value = []
        user_subscriptions = MagicMock()
        user_subscriptions.list_subscriptions.return_value = [
            {"source": "github", "channel_id": 10, "status": "active", "frequency": "daily"}
        ]
        push_channels = MagicMock()
        push_channels.list_channels.return_value = [
            {
                "id": 10,
                "channel_type": "webhook",
                "target": "https://example.com/hook",
                "verified": True,
                "status": CHANNEL_STATUS_ACTIVE,
            }
        ]
        service = _service(
            briefing_subscriptions=briefing_subscriptions,
            user_subscriptions=user_subscriptions,
            push_channels=push_channels,
        )

        result = service.apply_plan(
            user={"user_id": 1, "email": "a@b.com"},
            user_id=1,
            email="a@b.com",
            sources=["github"],
            deliveries=[DeliveryTarget(kind="push_channel", channel_id=10)],
        )

        user_subscriptions.create_subscription.assert_not_called()
        assert len(result["deliveries"]) == 0

    def test_idempotency_key_passed_through(self) -> None:
        briefing_subscriptions = MagicMock()
        briefing_subscriptions.upsert_briefing_subscription.return_value = {"id": 1}
        service = _service(briefing_subscriptions=briefing_subscriptions)

        result = service.apply_plan(
            user={"user_id": 1, "email": "a@b.com"},
            user_id=1,
            email="a@b.com",
            sources=["github"],
            deliveries=[DeliveryTarget(kind="account_email")],
            idempotency_key="abc-123",
        )

        assert result["idempotency_key"] == "abc-123"

    def test_mask_target_obscures_email_local_part(self) -> None:
        service = _service()
        masked = service._mask_target(
            {"channel_type": "email", "target": "alice@example.com"}
        )
        assert masked == "al***@example.com"

    def test_mask_target_obscures_long_non_email(self) -> None:
        service = _service()
        masked = service._mask_target(
            {"channel_type": "telegram", "target": "1234567890123456"}
        )
        assert masked.startswith("123456")
        assert masked.endswith("123456")
        assert "***" in masked

    def test_multiple_sources_with_multiple_channels(self) -> None:
        briefing_subscriptions = MagicMock()
        briefing_subscriptions.get_user_briefing_subscriptions.return_value = []
        briefing_subscriptions.upsert_briefing_subscription.return_value = {"id": 1}
        user_subscriptions = MagicMock()
        user_subscriptions.list_subscriptions.return_value = []
        user_subscriptions.create_subscription.return_value = {"id": 2}
        push_channels = MagicMock()
        push_channels.list_channels.return_value = [
            {
                "id": 10,
                "channel_type": "telegram",
                "target": "@alice",
                "verified": True,
                "status": CHANNEL_STATUS_ACTIVE,
            },
            {
                "id": 11,
                "channel_type": "discord",
                "target": "#channel",
                "verified": True,
                "status": CHANNEL_STATUS_ACTIVE,
            },
        ]
        service = _service(
            briefing_subscriptions=briefing_subscriptions,
            user_subscriptions=user_subscriptions,
            push_channels=push_channels,
        )

        result = service.apply_plan(
            user={"user_id": 1, "email": "a@b.com", "membership_tier": "member"},
            user_id=1,
            email="a@b.com",
            sources=["github", "news"],
            deliveries=[
                DeliveryTarget(kind="account_email"),
                DeliveryTarget(kind="push_channel", channel_id=10),
                DeliveryTarget(kind="push_channel", channel_id=11),
            ],
        )

        assert set(result["sources"]) == {"github", "news"}
        assert len(result["deliveries"]) == 3
        assert user_subscriptions.create_subscription.call_count == 4  # 2 sources × 2 channels

    def test_account_email_status_is_already_active_when_all_sources_active(self) -> None:
        briefing_subscriptions = MagicMock()
        briefing_subscriptions.get_user_briefing_subscriptions.return_value = [
            {"source": "github"}
        ]
        briefing_subscriptions.upsert_briefing_subscription.return_value = {"id": 1}
        service = _service(briefing_subscriptions=briefing_subscriptions)

        result = service.apply_plan(
            user={"user_id": 1, "email": "a@b.com"},
            user_id=1,
            email="a@b.com",
            sources=["github"],
            deliveries=[DeliveryTarget(kind="account_email")],
        )

        assert result["deliveries"][0]["status"] == "already_active"
