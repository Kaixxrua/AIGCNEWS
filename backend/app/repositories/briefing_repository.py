from __future__ import annotations

from typing import Any, Protocol


class BriefingWriter(Protocol):
    """Write boundary for generated briefing content."""

    def save_briefing(
        self,
        date_str: str,
        content: str,
        *,
        content_zh: str = "",
        content_en: str = "",
    ) -> int: ...


class BriefingReader(Protocol):
    """Read boundary for generated briefing content."""

    def get_latest_briefing(self) -> dict[str, Any] | None: ...

    def get_briefing_by_date(self, date_str: str) -> dict[str, Any] | None: ...

    def get_briefing(self, briefing_id: int) -> dict[str, Any] | None: ...

    def list_briefings(self, limit: int = 30) -> list[dict[str, Any]]: ...

    def list_recent_daily_briefings(self, limit: int = 7) -> list[dict[str, Any]]: ...


class BriefingContentRepository(BriefingWriter, BriefingReader, Protocol):
    """Combined content boundary used by briefing generation services."""


class BriefingSubscriptionWriter(Protocol):
    """Write boundary for a user's briefing subscriptions."""

    def upsert_briefing_subscription(
        self,
        user_id: int,
        email: str,
        source: str = "all",
    ) -> dict[str, Any]: ...

    def cancel_briefing_subscription(
        self,
        user_id: int,
        source: str = "all",
    ) -> bool: ...


class UserBriefingSubscriptionReader(Protocol):
    """Read boundary scoped to a user's active subscriptions."""

    def get_user_briefing_subscriptions(
        self,
        user_id: int,
    ) -> list[dict[str, Any]]: ...


class BriefingSubscriptionRepository(
    BriefingSubscriptionWriter,
    UserBriefingSubscriptionReader,
    Protocol,
):
    """Combined subscription boundary used by authenticated user routes."""


class ActiveBriefingSubscriberReader(Protocol):
    """Delivery-only boundary that may expose subscriber email addresses."""

    def get_active_subscribers(
        self,
        source: str = "all",
    ) -> list[dict[str, Any]]: ...


class BriefingDeliveryMarker(Protocol):
    """Idempotency write boundary for subscription briefing deliveries."""

    def mark_briefing_delivered(
        self,
        subscription_ids: list[int],
        briefing_id: int,
    ) -> None: ...


class BriefingDispatchSubscriptionRepository(
    ActiveBriefingSubscriberReader,
    BriefingDeliveryMarker,
    Protocol,
):
    """Combined boundary used by the daily dispatch job."""
