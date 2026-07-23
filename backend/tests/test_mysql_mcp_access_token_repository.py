from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.core.database import DatabaseLifecycle
from backend.app.repositories.mysql_mcp_access_token_repository import (
    MySQLMcpAccessTokenRepository,
)


class MySQLMcpAccessTokenRepositoryTests(unittest.TestCase):
    def test_create_locks_user_purges_revoked_history_and_returns_metadata(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.fetchone.side_effect = [
            {"id": 7},
            {
                "id": 21,
                "user_id": 7,
                "token_hint": "aigc_mcp_abc...wxyz",
                "scopes_json": '["projects:favorites:read"]',
            },
        ]
        cursor.lastrowid = 21

        result = repository.create_user_mcp_token(
            user_id=7,
            token_hash="a" * 64,
            token_hint="aigc_mcp_abc...wxyz",
            scopes=["projects:favorites:read"],
            client_type="claude",
            client_label="Desktop",
        )

        executions = cursor.execute.call_args_list
        self.assertEqual(len(executions), 4)
        self.assertIn("FOR UPDATE", executions[0].args[0])
        self.assertEqual(executions[0].args[1], (7,))
        self.assertIn("DELETE FROM user_mcp_tokens", executions[1].args[0])
        self.assertIn("revoked_at IS NOT NULL", executions[1].args[0])
        insert_params = executions[2].args[1]
        self.assertEqual(insert_params[0:3], (7, "a" * 64, "aigc_mcp_abc...wxyz"))
        self.assertEqual(insert_params[3], '["projects:favorites:read"]')
        self.assertEqual(result["replaced_count"], 0)
        self.assertEqual(result["token_metadata"]["id"], 21)
        self.assertNotIn("token_hash", result["token_metadata"])
        connection.commit.assert_called_once_with()
        connection.rollback.assert_not_called()
        connection.close.assert_called_once_with()

    def test_create_missing_user_rolls_back(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.fetchone.return_value = None

        with self.assertRaisesRegex(ValueError, "user does not exist"):
            repository.create_user_mcp_token(
                user_id=7,
                token_hash="a" * 64,
                token_hint="hint",
                scopes=["projects:favorites:read"],
                client_type="claude",
            )

        self.assertEqual(cursor.execute.call_count, 1)
        connection.commit.assert_not_called()
        connection.rollback.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_list_is_owner_scoped_active_and_ordered(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.fetchall.return_value = [
            {"id": 21, "scopes_json": "not-json", "created_at": None}
        ]

        result = repository.list_user_mcp_tokens(user_id=7)

        sql, params = cursor.execute.call_args.args
        self.assertIn("user_id = %s", sql)
        self.assertIn("revoked_at IS NULL", sql)
        self.assertIn("deleted_at IS NULL", sql)
        self.assertIn("ORDER BY created_at DESC, id DESC", sql)
        self.assertEqual(params, (7,))
        self.assertEqual(result[0]["scopes"], [])
        connection.commit.assert_not_called()
        connection.close.assert_called_once_with()

    def test_lookup_filters_inactive_tokens_and_throttles_last_use(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.fetchone.return_value = {
            "token_id": 21,
            "user_id": 7,
            "scopes_json": '["projects:favorites:read"]',
            "email": "reader@example.com",
            "role": "user",
        }

        result = repository.get_user_by_mcp_token_hash("a" * 64)

        lookup, update = cursor.execute.call_args_list
        self.assertIn("t.token_hash = %s", lookup.args[0])
        self.assertIn("t.revoked_at IS NULL", lookup.args[0])
        self.assertIn("t.deleted_at IS NULL", lookup.args[0])
        self.assertIn("t.expires_at > UTC_TIMESTAMP()", lookup.args[0])
        self.assertEqual(lookup.args[1], ("a" * 64,))
        self.assertIn("INTERVAL 5 MINUTE", update.args[0])
        self.assertEqual(update.args[1], (21,))
        self.assertEqual(result["scopes"], ["projects:favorites:read"])
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_lookup_missing_token_does_not_update(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.fetchone.return_value = None

        self.assertIsNone(repository.get_user_by_mcp_token_hash("a" * 64))

        self.assertEqual(cursor.execute.call_count, 1)
        connection.commit.assert_called_once_with()

    def test_delete_is_owner_scoped_soft_delete(self) -> None:
        repository, connection, cursor = self._repository()
        cursor.rowcount = 1

        self.assertTrue(repository.delete_user_mcp_token(user_id=7, token_id=21))

        sql, params = cursor.execute.call_args.args
        self.assertIn("revoked_at = COALESCE", sql)
        self.assertIn("deleted_at = UTC_TIMESTAMP()", sql)
        self.assertIn("user_id = %s", sql)
        self.assertIn("deleted_at IS NULL", sql)
        self.assertEqual(params, (21, 7))
        connection.commit.assert_called_once_with()
        connection.close.assert_called_once_with()

    def test_mutation_failure_rolls_back_and_preserves_base_exception(self) -> None:
        operations = (
            lambda repository: repository.get_user_by_mcp_token_hash("a" * 64),
            lambda repository: repository.delete_user_mcp_token(
                user_id=7,
                token_id=21,
            ),
        )
        for operation in operations:
            with self.subTest(operation=operation):
                repository, connection, cursor = self._repository()
                error = KeyboardInterrupt("interrupted")
                cursor.execute.side_effect = error

                with self.assertRaises(KeyboardInterrupt) as context:
                    operation(repository)

                self.assertIs(context.exception, error)
                connection.commit.assert_not_called()
                connection.rollback.assert_called_once_with()
                connection.close.assert_called_once_with()

    @staticmethod
    def _repository():
        cursor = MagicMock()
        cursor_context = MagicMock()
        cursor_context.__enter__.return_value = cursor
        connection = MagicMock()
        connection.cursor.return_value = cursor_context
        pool = MagicMock()
        pool.connection.return_value = connection
        database = DatabaseLifecycle(MagicMock(return_value=pool))
        return MySQLMcpAccessTokenRepository(database), connection, cursor


if __name__ == "__main__":
    unittest.main()
