from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.services.mcp.admin_service import McpAdminService, project_server


class McpAdminServiceTests(unittest.TestCase):
    def test_safe_projection_does_not_retain_raw_token(self) -> None:
        secret = "internal-secret-token"
        projection = project_server(
            {
                "id": 1,
                "server_key": "example",
                "display_name": "Example",
                "url": "https://example.test/mcp",
                "auth_type": "bearer",
                "auth_token": secret,
                "enabled": True,
            }
        )

        self.assertTrue(projection.auth_token_configured)
        self.assertEqual(projection.auth_token_masked, "inte****oken")
        self.assertNotIn(secret, repr(projection))
        self.assertFalse(hasattr(projection, "auth_token"))

    def test_connection_test_reads_internal_row_then_persists_result(self) -> None:
        row = {"id": 42, "auth_token": "internal-secret"}
        updated = {"id": 42, "last_test_status": "success"}
        store = MagicMock()
        store.get_mcp_server_config.return_value = row
        store.update_mcp_server_test_result.return_value = updated
        tester = MagicMock(
            return_value={"status": "success", "message": "ready", "tools": []}
        )

        outcome = McpAdminService(store).test_connection(42, tester)

        self.assertIsNotNone(outcome)
        tester.assert_called_once_with(row)
        store.update_mcp_server_test_result.assert_called_once_with(
            42,
            {"status": "success", "message": "ready", "tools": []},
        )
        self.assertEqual(outcome.server, updated)

    def test_missing_connection_target_returns_none_without_testing(self) -> None:
        store = MagicMock()
        store.get_mcp_server_config.return_value = None
        tester = MagicMock()

        outcome = McpAdminService(store).test_connection(42, tester)

        self.assertIsNone(outcome)
        tester.assert_not_called()
        store.update_mcp_server_test_result.assert_not_called()


if __name__ == "__main__":
    unittest.main()
