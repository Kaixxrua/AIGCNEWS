from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.repositories.mcp_access_token_repository import (
    McpAccessTokenAuthenticator,
    McpAccessTokenManager,
)


class McpAccessTokenRepositoryContractTests(unittest.TestCase):
    def test_manager_spec_does_not_expose_authentication_lookup(self) -> None:
        repository = MagicMock(spec=McpAccessTokenManager)
        repository.list_user_mcp_tokens.return_value = [{"id": 42}]
        repository.delete_user_mcp_token.return_value = True

        self.assertEqual(repository.list_user_mcp_tokens(user_id=7), [{"id": 42}])
        self.assertTrue(repository.delete_user_mcp_token(user_id=7, token_id=42))
        with self.assertRaises(AttributeError):
            repository.get_user_by_mcp_token_hash("digest")

    def test_authenticator_spec_does_not_expose_management(self) -> None:
        repository = MagicMock(spec=McpAccessTokenAuthenticator)
        repository.get_user_by_mcp_token_hash.return_value = {
            "user_id": 7,
            "scopes": ["projects:favorites:read"],
        }

        self.assertEqual(
            repository.get_user_by_mcp_token_hash("digest"),
            {"user_id": 7, "scopes": ["projects:favorites:read"]},
        )
        with self.assertRaises(AttributeError):
            repository.list_user_mcp_tokens(user_id=7)
        with self.assertRaises(AttributeError):
            repository.delete_user_mcp_token(user_id=7, token_id=42)


if __name__ == "__main__":
    unittest.main()
