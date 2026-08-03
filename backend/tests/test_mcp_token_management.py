from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_auth
from backend.app.api.dependencies import get_mcp_access_token_repository


class McpTokenManagementTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        app.include_router(routes_auth.router, prefix="/api")

        async def user():
            return {"user_id": 7, "email": "user@example.com", "role": "user"}

        app.dependency_overrides[routes_auth.RequireUser] = user
        self.repository = MagicMock()
        app.dependency_overrides[get_mcp_access_token_repository] = (
            lambda: self.repository
        )
        self.client = TestClient(app)

    def test_create_contract_and_no_cache_headers(self) -> None:
        repository = self.repository
        repository.create_user_mcp_token.return_value = {
            "token_metadata": {
                "id": 9,
                "token_hint": "aigc_mcp_abc...wxyz",
                "scopes": ["projects:favorites:read"],
                "client_type": "claude",
                "client_label": "Desktop",
                "expires_at": None,
                "revoked_at": None,
                "deleted_at": None,
            },
            "replaced_count": 0,
        }
        response = self.client.post(
                "/api/auth/me/mcp-tokens",
                json={
                    "client_type": "claude",
                    "client_label": "Desktop",
                    "scopes": ["projects:favorites:read"],
                },
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["token"].startswith("aigc_mcp_"))
        self.assertEqual(response.json()["replaced_count"], 0)
        self.assertEqual(response.json()["token_metadata"]["client_type"], "claude")
        repository.create_user_mcp_token.assert_called_once()
        self.assertNotIn("multi_open", repository.create_user_mcp_token.call_args.kwargs)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")

    def test_rejects_unknown_scope_and_expired_request(self) -> None:
        unknown = self.client.post(
            "/api/auth/me/mcp-tokens",
            json={"client_type": "claude", "scopes": ["admin:all"]},
        )
        expired = self.client.post(
            "/api/auth/me/mcp-tokens",
            json={
                "client_type": "claude",
                "scopes": ["projects:favorites:read"],
                "expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            },
        )
        self.assertEqual(unknown.status_code, 422)
        self.assertEqual(expired.status_code, 422)

    def test_list_contract_and_no_cache_headers(self) -> None:
        repository = self.repository
        repository.list_user_mcp_tokens.return_value = [
            {
                "id": 9,
                "token_hint": "aigc_mcp_abc...wxyz",
                "scopes": ["projects:favorites:read"],
                "client_type": "claude",
                "client_label": "Desktop",
                "expires_at": None,
                "revoked_at": None,
                "deleted_at": None,
            }
        ]
        response = self.client.get("/api/auth/me/mcp-tokens")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]["token_hint"], "aigc_mcp_abc...wxyz")
        repository.list_user_mcp_tokens.assert_called_once_with(user_id=7)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["pragma"], "no-cache")

    def test_old_management_path_is_not_exposed(self) -> None:
        self.assertEqual(self.client.get("/api/auth/mcp-tokens").status_code, 404)

    def test_delete_uses_soft_delete_repository_operation(self) -> None:
        repository = self.repository
        repository.delete_user_mcp_token.return_value = True
        response = self.client.delete("/api/auth/me/mcp-tokens/11")
        self.assertEqual(response.status_code, 200)
        repository.delete_user_mcp_token.assert_called_once_with(user_id=7, token_id=11)
        self.assertEqual(response.headers["pragma"], "no-cache")


if __name__ == "__main__":
    unittest.main()
