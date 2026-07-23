from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.core.database import DatabaseLifecycle
from backend.app.repositories.mysql_runtime_provider_repository import (
    MySQLRuntimeProviderSettingRepository,
)


class MySQLRuntimeProviderSettingRepositoryTests(unittest.TestCase):
    def test_reader_normalizes_provider_and_returns_internal_secret(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {
            "provider": "openai",
            "base_url": "https://example.test/v1",
            "api_key": "internal-key",
            "model_name": "model",
        }
        database.connection.return_value.__enter__.return_value = connection
        repository = MySQLRuntimeProviderSettingRepository(database)

        result = repository.get_runtime_provider_setting(" OpenAI ")

        self.assertEqual(result["api_key"], "internal-key")
        self.assertEqual(cursor.execute.call_args.args[1], ("openai",))
        connection.commit.assert_called_once_with()

    def test_blank_key_is_preserved_in_one_transaction(self) -> None:
        repository, database, _, cursor = self._repository()
        cursor.fetchone.side_effect = [
            {"api_key": "existing-key"},
            {
                "provider": "openai",
                "base_url": "https://example.test/v1",
                "api_key": "existing-key",
                "model_name": "model",
            },
        ]

        result = repository.upsert_runtime_provider_setting(
            " OpenAI ",
            " https://example.test/v1 ",
            "  ",
            False,
            " model ",
        )

        self.assertEqual(result["api_key"], "existing-key")
        self.assertEqual(len(cursor.execute.call_args_list), 4)
        self.assertIn("FOR UPDATE", cursor.execute.call_args_list[0].args[0])
        self.assertIn("DELETE FROM runtime_provider_settings", cursor.execute.call_args_list[1].args[0])
        insert_params = cursor.execute.call_args_list[2].args[1]
        self.assertEqual(
            insert_params,
            ("openai", "https://example.test/v1", "existing-key", "model"),
        )
        database.transaction.assert_called_once_with()
        database.connection.assert_not_called()

    def test_clear_key_overrides_existing_secret(self) -> None:
        repository, _, _, cursor = self._repository()
        cursor.fetchone.side_effect = [
            {"api_key": "existing-key"},
            {"provider": "ollama", "api_key": None},
        ]

        result = repository.upsert_runtime_provider_setting(
            "ollama",
            api_key="replacement",
            clear_api_key=True,
        )

        self.assertIsNone(result["api_key"])
        self.assertIsNone(cursor.execute.call_args_list[2].args[1][2])

    def test_transaction_context_preserves_original_failure(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        error = RuntimeError("insert failed")
        database.transaction.return_value.__enter__.side_effect = error
        repository = MySQLRuntimeProviderSettingRepository(database)

        with self.assertRaises(RuntimeError) as caught:
            repository.upsert_runtime_provider_setting("openai")

        self.assertIs(caught.exception, error)

    @staticmethod
    def _repository():
        database = MagicMock(spec=DatabaseLifecycle)
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        database.transaction.return_value.__enter__.return_value = connection
        return (
            MySQLRuntimeProviderSettingRepository(database),
            database,
            connection,
            cursor,
        )


if __name__ == "__main__":
    unittest.main()
