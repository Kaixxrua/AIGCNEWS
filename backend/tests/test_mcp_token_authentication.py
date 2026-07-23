from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.core import auth


class McpTokenAuthenticationTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        repository = MagicMock()
        self.repository = repository
        app.dependency_overrides[auth.get_mcp_access_token_authenticator] = (
            lambda: repository
        )

        @app.get("/mcp-auth")
        async def read_auth(user=auth.Depends(auth.OptionalMcpUser)):
            if user is None:
                return {"anonymous": True}
            return {
                "user_id": user["user_id"],
                "scopes": sorted(user["scopes"]),
            }

        self.client = TestClient(app)

    def test_missing_credentials_are_anonymous(self) -> None:
        response = self.client.get("/mcp-auth")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"anonymous": True})
        self.repository.get_user_by_mcp_token_hash.assert_not_called()

    def test_malformed_and_unknown_tokens_are_rejected(self) -> None:
        malformed = self.client.get(
            "/mcp-auth",
            headers={"Authorization": "Basic abc"},
        )
        self.repository.get_user_by_mcp_token_hash.return_value = None
        unknown = self.client.get(
            "/mcp-auth",
            headers={"Authorization": "Bearer raw-secret"},
        )

        self.assertEqual(malformed.status_code, 401)
        self.assertEqual(unknown.status_code, 401)
        self.assertEqual(unknown.headers["www-authenticate"], "Bearer")
        self.repository.get_user_by_mcp_token_hash.assert_called_once_with(
            auth.hash_mcp_token("raw-secret")
        )

    def test_valid_scopes_become_frozenset_without_raw_token_lookup(self) -> None:
        self.repository.get_user_by_mcp_token_hash.return_value = {
            "user_id": 7,
            "scopes": ["projects:favorites:read"],
        }

        response = self.client.get(
            "/mcp-auth",
            headers={"Authorization": "Bearer raw-secret"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"user_id": 7, "scopes": ["projects:favorites:read"]},
        )
        digest = self.repository.get_user_by_mcp_token_hash.call_args.args[0]
        self.assertEqual(digest, auth.hash_mcp_token("raw-secret"))
        self.assertNotEqual(digest, "raw-secret")

    def test_malformed_scope_context_is_rejected(self) -> None:
        self.repository.get_user_by_mcp_token_hash.return_value = {
            "user_id": 7,
            "scopes": "projects:favorites:read",
        }

        response = self.client.get(
            "/mcp-auth",
            headers={"Authorization": "Bearer raw-secret"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "MCP Token 权限无效"})


if __name__ == "__main__":
    unittest.main()
