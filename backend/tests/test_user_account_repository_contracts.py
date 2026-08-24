from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.repositories.user_account_repository import (
    UserAccountAdminReader,
    UserAccountReader,
    UserAccountWriter,
    UserStatisticsReader,
)


class UserAccountRepositoryContractTests(unittest.TestCase):
    def test_reader_spec_does_not_expose_writes_or_statistics(self) -> None:
        repository = MagicMock(spec=UserAccountReader)
        repository.get_user_by_email.return_value = {
            "id": 42,
            "hashed_password": "internal-hash",
        }

        self.assertEqual(
            repository.get_user_by_email("reader@example.com"),
            {"id": 42, "hashed_password": "internal-hash"},
        )
        with self.assertRaises(AttributeError):
            repository.create_user_with_email("reader@example.com", "hash")
        with self.assertRaises(AttributeError):
            repository.get_user_count()

    def test_writer_spec_preserves_defaults_and_keyword_password_update(self) -> None:
        repository = MagicMock(spec=UserAccountWriter)
        repository.create_user.return_value = 42
        repository.create_user_with_email.return_value = 43
        repository.update_user_password.return_value = 1

        self.assertEqual(repository.create_user("13800000000", "reader", "hash"), 42)
        self.assertEqual(
            repository.create_user_with_email("reader@example.com", "hash"),
            43,
        )
        self.assertEqual(
            repository.update_user_password(
                user_id=43,
                email="reader@example.com",
                hashed_password="new-hash",
            ),
            1,
        )
        with self.assertRaises(AttributeError):
            repository.get_user_by_email("reader@example.com")

    def test_statistics_spec_does_not_expose_account_rows(self) -> None:
        repository = MagicMock(spec=UserStatisticsReader)
        repository.get_user_count.return_value = 10
        repository.get_today_registered_user_count.return_value = 2
        repository.get_effective_member_count.return_value = 4

        self.assertEqual(repository.get_user_count(), 10)
        self.assertEqual(repository.get_today_registered_user_count(), 2)
        self.assertEqual(repository.get_effective_member_count(), 4)
        with self.assertRaises(AttributeError):
            repository.get_user_by_email("reader@example.com")
        with self.assertRaises(AttributeError):
            repository.update_user_password(
                user_id=42,
                email="reader@example.com",
                hashed_password="hash",
            )

    def test_admin_reader_spec_exposes_listing_without_writes(self) -> None:
        repository = MagicMock(spec=UserAccountAdminReader)
        repository.list_users.return_value = ([{"id": 42}], 1)

        self.assertEqual(
            repository.list_users(query="reader", page=2, page_size=50),
            ([{"id": 42}], 1),
        )
        repository.list_users.assert_called_once_with(
            query="reader", page=2, page_size=50
        )
        with self.assertRaises(AttributeError):
            repository.set_membership_tier(user_id=42, tier="member")
        with self.assertRaises(AttributeError):
            repository.get_user_by_email("reader@example.com")


if __name__ == "__main__":
    unittest.main()
