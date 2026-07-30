from __future__ import annotations

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from backend.app.repositories.mcp_server_repository import McpServerConfigConflictError
from backend.app.services.mcp.admin_service import (
    McpAdminConflictError,
    McpAdminNotFoundError,
    McpAdminService,
    McpAdminValidationError,
    project_server,
)


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

    def test_crud_commands_normalize_project_and_map_domain_outcomes(self) -> None:
        row = {
            "id": 42,
            "server_key": "example",
            "display_name": "Example MCP",
            "url": "https://example.test/mcp",
            "enabled": True,
        }
        store = MagicMock()
        store.list_mcp_server_configs.return_value = [row]
        store.create_mcp_server_config.return_value = row
        store.update_mcp_server_config.return_value = row
        store.delete_mcp_server_config.return_value = True
        service = McpAdminService(store)
        values = {
            "server_key": " Example ",
            "display_name": " Example MCP ",
            "description": " desc ",
            "url": "https://example.test/mcp",
            "transport": "streamable_http",
            "auth_type": "bearer",
            "auth_token": "secret",
            "clear_auth_token": False,
            "enabled": True,
        }

        with patch(
            "backend.app.services.mcp.admin_service.validate_mcp_http_url",
            return_value="https://example.test/mcp",
        ):
            listed = asyncio.run(service.list_servers())
            created = asyncio.run(service.create_server(values))
            updated = asyncio.run(service.update_server(42, values))
            asyncio.run(service.delete_server(42))

        self.assertEqual(listed[0].id, 42)
        self.assertEqual(created.server_key, "example")
        self.assertEqual(updated.id, 42)
        expected_payload = {
            "server_key": "example",
            "display_name": "Example MCP",
            "description": "desc",
            "url": "https://example.test/mcp",
            "transport": "streamable_http",
            "auth_type": "bearer",
            "auth_token": "secret",
            "clear_auth_token": False,
            "enabled": True,
        }
        store.create_mcp_server_config.assert_called_once_with(expected_payload)
        store.update_mcp_server_config.assert_called_once_with(42, expected_payload)
        store.delete_mcp_server_config.assert_called_once_with(42)

        store.create_mcp_server_config.side_effect = McpServerConfigConflictError()
        with self.assertRaisesRegex(McpAdminConflictError, "server_key 已存在"):
            with patch(
                "backend.app.services.mcp.admin_service.validate_mcp_http_url",
                return_value="https://example.test/mcp",
            ):
                asyncio.run(service.create_server(values))

        store.update_mcp_server_config.side_effect = None
        store.update_mcp_server_config.return_value = None
        with self.assertRaisesRegex(McpAdminNotFoundError, "配置不存在"):
            with patch(
                "backend.app.services.mcp.admin_service.validate_mcp_http_url",
                return_value="https://example.test/mcp",
            ):
                asyncio.run(service.update_server(42, values))

        store.delete_mcp_server_config.return_value = False
        with self.assertRaisesRegex(McpAdminNotFoundError, "配置不存在"):
            asyncio.run(service.delete_server(42))

    def test_invalid_payload_is_rejected_before_repository_calls(self) -> None:
        store = MagicMock()
        service = McpAdminService(store)

        with self.assertRaisesRegex(McpAdminValidationError, "server_key"):
            asyncio.run(
                service.create_server(
                    {
                        "server_key": "!",
                        "display_name": "Example",
                        "url": "https://example.test/mcp",
                    }
                )
            )

        store.create_mcp_server_config.assert_not_called()

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
