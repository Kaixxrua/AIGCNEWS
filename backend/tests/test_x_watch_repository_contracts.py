from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.repositories.x_watch_repository import (
    XWatchAccountReader,
    XWatchAccountSeeder,
    XWatchAccountWriter,
    XWatchHandleReader,
    XWatchTestResultWriter,
)


class XWatchAccountRepositoryContractTests(unittest.TestCase):
    def test_seeder_spec_does_not_expose_reads_or_writes(self) -> None:
        repository = MagicMock(spec=XWatchAccountSeeder)

        repository._seed_default_x_watch_accounts()

        repository._seed_default_x_watch_accounts.assert_called_once_with()
        with self.assertRaises(AttributeError):
            repository.list_x_watch_accounts()
        with self.assertRaises(AttributeError):
            repository.create_x_watch_account({})

    def test_reader_spec_does_not_expose_mutations(self) -> None:
        repository = MagicMock(spec=XWatchAccountReader)
        repository.list_x_watch_accounts.return_value = [{"id": 42}]
        repository.get_x_watch_account.return_value = {
            "id": 42,
            "screen_name": "openai",
        }

        self.assertEqual(repository.list_x_watch_accounts(), [{"id": 42}])
        self.assertEqual(
            repository.get_x_watch_account(42),
            {"id": 42, "screen_name": "openai"},
        )
        with self.assertRaises(AttributeError):
            repository.delete_x_watch_account(42)
        with self.assertRaises(AttributeError):
            repository.list_enabled_x_handles()

    def test_writer_spec_does_not_expose_reads_or_test_results(self) -> None:
        repository = MagicMock(spec=XWatchAccountWriter)
        repository.create_x_watch_account.return_value = {"id": 42}
        repository.update_x_watch_account.return_value = {"id": 42}
        repository.delete_x_watch_account.return_value = True
        payload = {"screen_name": "openai"}

        self.assertEqual(repository.create_x_watch_account(payload), {"id": 42})
        self.assertEqual(
            repository.update_x_watch_account(42, payload),
            {"id": 42},
        )
        self.assertTrue(repository.delete_x_watch_account(42))
        with self.assertRaises(AttributeError):
            repository.get_x_watch_account(42)
        with self.assertRaises(AttributeError):
            repository.update_x_watch_test_result(42, {})

    def test_test_result_writer_spec_does_not_expose_config_mutations(self) -> None:
        repository = MagicMock(spec=XWatchTestResultWriter)
        result = {"status": "succeeded", "message": "pulled 3 tweets"}
        repository.update_x_watch_test_result.return_value = {"id": 42}

        self.assertEqual(
            repository.update_x_watch_test_result(42, result),
            {"id": 42},
        )
        with self.assertRaises(AttributeError):
            repository.update_x_watch_account(42, {})
        with self.assertRaises(AttributeError):
            repository.list_x_watch_accounts()

    def test_handle_reader_spec_only_exposes_enabled_handles(self) -> None:
        repository = MagicMock(spec=XWatchHandleReader)
        repository.list_enabled_x_handles.return_value = ["openai", "anthropicai"]

        self.assertEqual(repository.list_enabled_x_handles(), ["openai", "anthropicai"])
        with self.assertRaises(AttributeError):
            repository.list_x_watch_accounts()
        with self.assertRaises(AttributeError):
            repository.create_x_watch_account({})


if __name__ == "__main__":
    unittest.main()
