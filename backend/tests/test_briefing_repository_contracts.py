from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.repositories.briefing_repository import (
    ActiveBriefingSubscriberReader,
    BriefingContentRepository,
    BriefingReader,
    BriefingSubscriptionRepository,
    BriefingSubscriptionWriter,
    BriefingWriter,
    UserBriefingSubscriptionReader,
)


class BriefingRepositoryContractTests(unittest.TestCase):
    def test_writer_spec_does_not_expose_reads(self) -> None:
        repository = MagicMock(spec=BriefingWriter)
        repository.save_briefing.return_value = 42

        self.assertEqual(repository.save_briefing("2026-07-22", "content"), 42)
        with self.assertRaises(AttributeError):
            repository.list_briefings()

    def test_reader_spec_does_not_expose_writes(self) -> None:
        repository = MagicMock(spec=BriefingReader)
        repository.get_latest_briefing.return_value = {"id": 42}
        repository.get_briefing_by_date.return_value = {"id": 42}
        repository.get_briefing.return_value = {"id": 42}
        repository.list_briefings.return_value = [{"id": 42}]

        self.assertEqual(repository.get_latest_briefing(), {"id": 42})
        self.assertEqual(repository.get_briefing_by_date("2026-07-22"), {"id": 42})
        self.assertEqual(repository.get_briefing(42), {"id": 42})
        self.assertEqual(repository.list_briefings(limit=7), [{"id": 42}])
        with self.assertRaises(AttributeError):
            repository.save_briefing("2026-07-22", "content")

    def test_subscription_capabilities_keep_delivery_emails_isolated(self) -> None:
        writer = MagicMock(spec=BriefingSubscriptionWriter)
        reader = MagicMock(spec=UserBriefingSubscriptionReader)
        delivery_reader = MagicMock(spec=ActiveBriefingSubscriberReader)

        writer.upsert_briefing_subscription.return_value = {"id": 42}
        reader.get_user_briefing_subscriptions.return_value = [{"id": 42}]
        delivery_reader.get_active_subscribers.return_value = [
            {"email": "reader@example.com"}
        ]

        self.assertEqual(
            writer.upsert_briefing_subscription(7, "reader@example.com"),
            {"id": 42},
        )
        self.assertEqual(reader.get_user_briefing_subscriptions(7), [{"id": 42}])
        self.assertEqual(
            delivery_reader.get_active_subscribers(),
            [{"email": "reader@example.com"}],
        )
        with self.assertRaises(AttributeError):
            reader.get_active_subscribers()
        with self.assertRaises(AttributeError):
            writer.get_active_subscribers()
        with self.assertRaises(AttributeError):
            delivery_reader.upsert_briefing_subscription(7, "reader@example.com")


if __name__ == "__main__":
    unittest.main()
