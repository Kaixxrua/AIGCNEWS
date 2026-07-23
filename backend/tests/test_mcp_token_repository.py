from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock

if "pymysql" not in sys.modules:
    pymysql_module = types.ModuleType("pymysql")
    pymysql_module.cursors = types.SimpleNamespace(DictCursor=object)
    pymysql_module.err = types.SimpleNamespace(OperationalError=Exception, InternalError=Exception)
    sys.modules["pymysql"] = pymysql_module

if "DBUtils.PooledDB" not in sys.modules:
    dbutils_module = types.ModuleType("DBUtils")
    pooled_db_module = types.ModuleType("DBUtils.PooledDB")
    pooled_db_module.PooledDB = object
    sys.modules["DBUtils"] = dbutils_module
    sys.modules["DBUtils.PooledDB"] = pooled_db_module

if "backend.app.core.config" not in sys.modules:
    config_module = types.ModuleType("backend.app.core.config")
    config_module.settings = types.SimpleNamespace(
        mcp_github_fallback_enabled=True,
        mcp_github_fallback_use_token=False,
        mcp_github_fallback_timeout_seconds=8.0,
        github_token="",
    )
    sys.modules["backend.app.core.config"] = config_module

repository_module = sys.modules.get("backend.app.repositories.mysql_repo")
if repository_module is not None and getattr(repository_module, "MySQLRepository", None) is object:
    del sys.modules["backend.app.repositories.mysql_repo"]

from backend.app.core.database import DatabaseLifecycle
from backend.app.repositories.mysql_mcp_access_token_repository import (
    MySQLMcpAccessTokenRepository,
)


class McpTokenRepositoryTests(unittest.TestCase):
    def test_create_purges_only_users_revoked_tokens_before_insert(self) -> None:
        cursor = MagicMock()
        cursor.fetchone.side_effect = [
            {"id": 7},
            {
                "id": 21,
                "user_id": 7,
                "token_hint": "aigc_mcp_abc...wxyz",
                "scopes_json": '["projects:favorites:read"]',
                "client_type": "claude",
                "client_label": "Desktop",
                "expires_at": None,
                "revoked_at": None,
                "deleted_at": None,
                "created_at": None,
                "last_used_at": None,
            },
        ]
        cursor.lastrowid = 21
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        database = MagicMock(spec=DatabaseLifecycle)
        database.transaction.return_value.__enter__.return_value = connection
        repository = MySQLMcpAccessTokenRepository(database)

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
        purge_sql, purge_params = executions[1].args
        self.assertIn("DELETE FROM user_mcp_tokens", purge_sql)
        self.assertIn("user_id = %s", purge_sql)
        self.assertIn("revoked_at IS NOT NULL", purge_sql)
        self.assertEqual(purge_params, (7,))
        self.assertNotIn("UPDATE user_mcp_tokens", "\n".join(call.args[0] for call in executions))
        self.assertEqual(result["replaced_count"], 0)
        self.assertEqual(result["token_metadata"]["id"], 21)
        database.transaction.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
