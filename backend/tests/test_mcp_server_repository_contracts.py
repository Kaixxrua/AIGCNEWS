from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.repositories.mcp_server_repository import (
    McpServerConfigReader,
    McpServerConfigSeeder,
    McpServerConfigWriter,
    McpServerTestResultWriter,
)


class McpServerConfigRepositoryContractTests(unittest.TestCase):
    def test_seeder_spec_does_not_expose_reads_or_writes(self) -> None:
        repository = MagicMock(spec=McpServerConfigSeeder)

        repository._seed_default_mcp_server_configs()

        repository._seed_default_mcp_server_configs.assert_called_once_with()
        with self.assertRaises(AttributeError):
            repository.list_mcp_server_configs()
        with self.assertRaises(AttributeError):
            repository.create_mcp_server_config({})

    def test_reader_spec_does_not_expose_mutations(self) -> None:
        repository = MagicMock(spec=McpServerConfigReader)
        repository.list_mcp_server_configs.return_value = [{"id": 42}]
        repository.get_mcp_server_config.return_value = {
            "id": 42,
            "auth_token": "internal-secret",
        }

        self.assertEqual(repository.list_mcp_server_configs(), [{"id": 42}])
        self.assertEqual(
            repository.get_mcp_server_config(42),
            {"id": 42, "auth_token": "internal-secret"},
        )
        with self.assertRaises(AttributeError):
            repository.delete_mcp_server_config(42)
        with self.assertRaises(AttributeError):
            repository.update_mcp_server_test_result(42, {})

    def test_writer_spec_does_not_expose_reads_or_test_results(self) -> None:
        repository = MagicMock(spec=McpServerConfigWriter)
        repository.create_mcp_server_config.return_value = {"id": 42}
        repository.update_mcp_server_config.return_value = {"id": 42}
        repository.delete_mcp_server_config.return_value = True
        payload = {"server_key": "example"}

        self.assertEqual(repository.create_mcp_server_config(payload), {"id": 42})
        self.assertEqual(
            repository.update_mcp_server_config(42, payload),
            {"id": 42},
        )
        self.assertTrue(repository.delete_mcp_server_config(42))
        with self.assertRaises(AttributeError):
            repository.get_mcp_server_config(42)
        with self.assertRaises(AttributeError):
            repository.update_mcp_server_test_result(42, {})

    def test_test_result_writer_spec_does_not_expose_config_mutations(self) -> None:
        repository = MagicMock(spec=McpServerTestResultWriter)
        result = {"status": "succeeded", "tools": []}
        repository.update_mcp_server_test_result.return_value = {"id": 42}

        self.assertEqual(
            repository.update_mcp_server_test_result(42, result),
            {"id": 42},
        )
        with self.assertRaises(AttributeError):
            repository.update_mcp_server_config(42, {})
        with self.assertRaises(AttributeError):
            repository.list_mcp_server_configs()


if __name__ == "__main__":
    unittest.main()
