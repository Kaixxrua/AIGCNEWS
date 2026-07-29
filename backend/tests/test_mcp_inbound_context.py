from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.services.mcp.inbound.context import McpAuthorizationContext
from backend.app.services.mcp.inbound.tools import McpToolContext


class McpInboundAuthorizationContextTests(unittest.TestCase):
    def test_anonymous_context_has_no_identity_or_scope(self) -> None:
        context = McpAuthorizationContext(None)

        self.assertFalse(context.is_authenticated)
        self.assertEqual(context.user_id, 0)
        self.assertFalse(context.has_scope("projects:favorites:read"))

    def test_authenticated_context_projects_identity_and_scope(self) -> None:
        user = {
            "user_id": "42",
            "scopes": frozenset({"projects:favorites:read"}),
        }
        context = McpAuthorizationContext(user)

        self.assertTrue(context.is_authenticated)
        self.assertEqual(context.user_id, 42)
        self.assertTrue(context.has_scope("projects:favorites:read"))
        self.assertFalse(context.has_scope("projects:favorites:write"))

    def test_tool_context_keeps_user_constructor_seam(self) -> None:
        user = {"user_id": 42, "scopes": frozenset()}
        tool_context = McpToolContext(
            user=user,
            documents=MagicMock(),
            papers=MagicMock(),
            rank_snapshots=MagicMock(),
            project_collection=MagicMock(),
            request=MagicMock(),
        )

        self.assertIs(tool_context.user, user)
        self.assertIs(tool_context.authorization.user, user)


if __name__ == "__main__":
    unittest.main()
