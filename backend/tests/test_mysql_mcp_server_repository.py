from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from backend.app.core.database import DatabaseLifecycle
from backend.app.repositories.mysql_mcp_server_repository import (
    MySQLMcpServerConfigRepository,
)


class MySQLMcpServerConfigRepositoryTests(unittest.TestCase):
    def test_list_seeds_nonblank_defaults_and_preserves_order(self) -> None:
        repository, connection, cursor = self._repository(
            defaults=(
                ("arxiv", "Arxiv MCP", " https://arxiv.example/mcp "),
                ("github", "GitHub MCP", ""),
            )
        )
        rows = [{"id": 42, "auth_token": "internal-token"}]
        cursor.fetchall.return_value = rows

        result = repository.list_mcp_server_configs()

        self.assertEqual(result, rows)
        self.assertIsNot(result, rows)
        seed_call, list_call = cursor.execute.call_args_list
        self.assertIn("INSERT IGNORE INTO mcp_server_configs", seed_call.args[0])
        self.assertEqual(
            seed_call.args[1],
            (
                "arxiv",
                "Arxiv MCP",
                "由环境变量初始化的 MCP Server，可在本页继续编辑。",
                "https://arxiv.example/mcp",
            ),
        )
        self.assertIn("auth_type, auth_token, enabled", list_call.args[0])
        self.assertIn(
            "ORDER BY enabled DESC, display_name ASC, id ASC",
            list_call.args[0],
        )
        self.assertEqual(connection.commit.call_count, 2)
        self.assertEqual(connection.close.call_count, 2)

    def test_seed_skips_blank_defaults_without_connecting(self) -> None:
        database = MagicMock(spec=DatabaseLifecycle)
        repository = MySQLMcpServerConfigRepository(
            database,
            (("arxiv", "Arxiv MCP", "  "),),
        )

        repository._seed_default_mcp_server_configs()

        database.transaction.assert_not_called()
        database.connection.assert_not_called()

    def test_seed_rolls_back_and_preserves_base_exception(self) -> None:
        repository, connection, cursor = self._repository(
            defaults=(("arxiv", "Arxiv MCP", "https://arxiv.example/mcp"),)
        )
        error = KeyboardInterrupt("seed interrupted")
        cursor.execute.side_effect = error

        with self.assertRaises(KeyboardInterrupt) as context:
            repository._seed_default_mcp_server_configs()

        self.assertIs(context.exception, error)
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_get_preserves_secret_projection_parameter_and_none(self) -> None:
        repository, connection, cursor = self._repository()
        row = {"id": 42, "auth_token": "internal-token"}
        cursor.fetchone.return_value = row

        result = repository.get_mcp_server_config(42)

        self.assertEqual(result, row)
        self.assertIsNot(result, row)
        sql, params = cursor.execute.call_args.args
        self.assertIn("auth_type, auth_token, enabled", sql)
        self.assertIn("WHERE id = %s", sql)
        self.assertIn("LIMIT 1", sql)
        self.assertEqual(params, (42,))
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

        cursor.fetchone.return_value = None
        self.assertIsNone(repository.get_mcp_server_config(7))

    def test_create_normalizes_fields_and_returns_inserted_row(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.lastrowid = 42
        created = {"id": 42, "auth_token": "secret"}
        cursor.fetchone.return_value = created

        result = repository.create_mcp_server_config(
            {
                "server_key": " Example ",
                "display_name": " Example MCP ",
                "description": " Description ",
                "url": " https://example.test/mcp ",
                "transport": " STREAMABLE_HTTP ",
                "auth_type": " BEARER ",
                "auth_token": " secret ",
                "enabled": False,
            }
        )

        self.assertEqual(result, created)
        insert_call = cursor.execute.call_args_list[0]
        self.assertIn("INSERT INTO mcp_server_configs", insert_call.args[0])
        self.assertEqual(
            insert_call.args[1],
            (
                "example",
                "Example MCP",
                "Description",
                "https://example.test/mcp",
                "streamable_http",
                "bearer",
                "secret",
                0,
            ),
        )
        self.assertEqual(cursor.execute.call_args_list[1].args[1], (42,))
        self.assertEqual(connection.commit.call_count, 2)
        self.assertEqual(connection.close.call_count, 2)

    def test_create_none_auth_clears_supplied_token(self) -> None:
        repository, _, cursor = self._repository()
        cursor.lastrowid = 42
        cursor.fetchone.return_value = {"id": 42}

        repository.create_mcp_server_config(
            {
                "server_key": "example",
                "display_name": "Example",
                "url": "https://example.test/mcp",
                "auth_type": "none",
                "auth_token": "must-not-persist",
            }
        )

        self.assertIsNone(cursor.execute.call_args_list[0].args[1][6])

    def test_create_rolls_back_and_preserves_base_exception(self) -> None:
        repository, connection, cursor = self._repository()
        error = KeyboardInterrupt("insert interrupted")
        cursor.execute.side_effect = error

        with self.assertRaises(KeyboardInterrupt) as context:
            repository.create_mcp_server_config({"server_key": "example"})

        self.assertIs(context.exception, error)
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_update_returns_none_without_write_when_missing(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.fetchone.return_value = None

        self.assertIsNone(repository.update_mcp_server_config(42, {}))

        self.assertEqual(cursor.execute.call_count, 1)
        self.assertEqual(connection.commit.call_count, 1)
        connection.rollback.assert_not_called()

    def test_update_blank_token_preserves_existing_token_and_fields(self) -> None:
        repository, connection, cursor = self._repository()
        existing = {
            "id": 42,
            "server_key": "example",
            "display_name": "Example MCP",
            "description": "Old description",
            "url": "https://example.test/mcp",
            "transport": "streamable_http",
            "auth_type": "bearer",
            "auth_token": "existing-secret",
            "enabled": 1,
        }
        refreshed = {**existing, "updated_at": "now"}
        cursor.fetchone.side_effect = [existing, refreshed]

        result = repository.update_mcp_server_config(42, {"auth_token": "  "})

        self.assertEqual(result, refreshed)
        update_call = cursor.execute.call_args_list[1]
        self.assertIn("updated_at = NOW()", update_call.args[0])
        self.assertEqual(
            update_call.args[1],
            (
                "example",
                "Example MCP",
                "Old description",
                "https://example.test/mcp",
                "streamable_http",
                "bearer",
                "existing-secret",
                1,
                42,
            ),
        )
        self.assertEqual(connection.commit.call_count, 3)

    def test_update_clear_and_none_auth_take_precedence(self) -> None:
        for payload in (
            {"clear_auth_token": True},
            {"auth_type": "none", "auth_token": "new-secret"},
        ):
            with self.subTest(payload=payload):
                repository, _, cursor = self._repository()
                existing = {
                    "id": 42,
                    "server_key": "example",
                    "display_name": "Example",
                    "url": "https://example.test/mcp",
                    "transport": "streamable_http",
                    "auth_type": "bearer",
                    "auth_token": "existing-secret",
                    "enabled": 1,
                }
                cursor.fetchone.side_effect = [existing, existing]

                repository.update_mcp_server_config(42, payload)

                params = cursor.execute.call_args_list[1].args[1]
                self.assertIsNone(params[6])

    def test_update_allows_explicit_empty_description(self) -> None:
        repository, _, cursor = self._repository()
        existing = {
            "id": 42,
            "server_key": "example",
            "display_name": "Example",
            "description": "Old",
            "url": "https://example.test/mcp",
            "transport": "streamable_http",
            "auth_type": "none",
            "enabled": 0,
        }
        cursor.fetchone.side_effect = [existing, existing]

        repository.update_mcp_server_config(42, {"description": ""})

        params = cursor.execute.call_args_list[1].args[1]
        self.assertEqual(params[2], "")
        self.assertEqual(params[7], 0)

    def test_update_rolls_back_and_preserves_base_exception(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.fetchone.return_value = {
            "id": 42,
            "server_key": "example",
            "display_name": "Example",
            "url": "https://example.test/mcp",
            "transport": "streamable_http",
            "auth_type": "none",
            "enabled": 1,
        }
        error = KeyboardInterrupt("update interrupted")
        cursor.execute.side_effect = [None, error]

        with self.assertRaises(KeyboardInterrupt) as context:
            repository.update_mcp_server_config(42, {})

        self.assertIs(context.exception, error)
        self.assertEqual(connection.commit.call_count, 1)
        connection.rollback.assert_called_once_with()
        self.assertEqual(connection.close.call_count, 2)

    def test_delete_is_parameterized_hard_delete(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.rowcount = 1

        self.assertTrue(repository.delete_mcp_server_config(42))

        self.assertEqual(
            cursor.execute.call_args.args,
            ("DELETE FROM mcp_server_configs WHERE id = %s", (42,)),
        )
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

        cursor.rowcount = 0
        self.assertFalse(repository.delete_mcp_server_config(7))

    def test_delete_rolls_back_and_preserves_base_exception(self) -> None:
        repository, connection, cursor = self._repository()
        error = KeyboardInterrupt("delete interrupted")
        cursor.execute.side_effect = error

        with self.assertRaises(KeyboardInterrupt) as context:
            repository.delete_mcp_server_config(42)

        self.assertIs(context.exception, error)
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_update_test_result_serializes_unicode_tools(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.rowcount = 1
        refreshed = {"id": 42, "last_test_status": "succeeded"}
        cursor.fetchone.return_value = refreshed
        tools = [{"name": "搜索", "description": "中文工具"}]

        result = repository.update_mcp_server_test_result(
            42,
            {"status": " SUCCEEDED ", "message": " ready ", "tools": tools},
        )

        self.assertEqual(result, refreshed)
        sql, params = cursor.execute.call_args_list[0].args
        self.assertIn("last_test_at = NOW()", sql)
        self.assertIn("updated_at = NOW()", sql)
        self.assertEqual(params[:2], ("succeeded", "ready"))
        self.assertEqual(json.loads(params[2]), tools)
        self.assertIn("搜索", params[2])
        self.assertEqual(params[3], 42)
        self.assertEqual(connection.commit.call_count, 2)

    def test_update_test_result_missing_row_uses_empty_tools_json(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.rowcount = 0

        result = repository.update_mcp_server_test_result(42, {})

        self.assertIsNone(result)
        self.assertEqual(cursor.execute.call_args.args[1], ("unknown", "", "[]", 42))
        self.assertEqual(cursor.execute.call_count, 1)
        connection.commit.assert_called_once_with()

    def test_update_test_result_rolls_back_and_preserves_base_exception(self) -> None:
        repository, connection, cursor = self._repository()
        error = KeyboardInterrupt("test result interrupted")
        cursor.execute.side_effect = error

        with self.assertRaises(KeyboardInterrupt) as context:
            repository.update_mcp_server_test_result(42, {})

        self.assertIs(context.exception, error)
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()

    @staticmethod
    def _repository(defaults=()):
        cursor = MagicMock()
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.cursor.return_value = cursor_context
        pool = MagicMock()
        pool.connection.return_value = connection
        database = DatabaseLifecycle(MagicMock(return_value=pool))
        repository = MySQLMcpServerConfigRepository(database, defaults)
        return repository, connection, cursor


if __name__ == "__main__":
    unittest.main()
