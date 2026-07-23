from __future__ import annotations

import inspect
import unittest
from typing import Any

from backend.app.repositories.conversation_repository import (
    ConversationCleanupWriter,
    ConversationMessageWriter,
    ConversationQuotaReader,
    ConversationReader,
    ConversationRepository,
    ConversationWriter,
)


def _without_annotations(function: Any) -> inspect.Signature:
    signature = inspect.signature(function)
    return signature.replace(
        parameters=[
            parameter.replace(annotation=inspect.Parameter.empty)
            for parameter in signature.parameters.values()
        ],
        return_annotation=inspect.Signature.empty,
    )


class ConversationRepositoryContractTests(unittest.TestCase):
    def test_combined_repository_preserves_narrow_capabilities(self) -> None:
        for capability in (
            ConversationReader,
            ConversationWriter,
            ConversationMessageWriter,
            ConversationQuotaReader,
            ConversationCleanupWriter,
        ):
            self.assertIn(capability, ConversationRepository.__mro__)

    def test_public_signatures_are_frozen(self) -> None:
        expected = {
            ConversationReader.get_owned_conversation_context: (
                "(self, *, user_id, conversation_id)"
            ),
            ConversationReader.list_conversations: (
                "(self, *, user_id, scope=None, page=1, page_size=20)"
            ),
            ConversationWriter.ensure_conversation: (
                "(self, *, user_id, scope='global', scope_key=None, title=None, "
                "keep_latest=10)"
            ),
            ConversationWriter.create_conversation: (
                "(self, *, user_id, scope='global', scope_key=None, title=None, "
                "keep_latest=10)"
            ),
            ConversationWriter.delete_owned_conversation: (
                "(self, *, user_id, conversation_id)"
            ),
            ConversationMessageWriter.append_message_pair: (
                "(self, *, user_id, conversation_id, scope, scope_key, user_message, "
                "assistant_content, assistant_thinking='', sources=None, attachments=None, "
                "parent_message_id=None, title=None, max_messages=10, max_conversations=10)"
            ),
            ConversationMessageWriter.delete_owned_message_branch: (
                "(self, *, user_id, message_id)"
            ),
            ConversationMessageWriter.prepare_owned_regeneration: (
                "(self, *, user_id, message_id)"
            ),
            ConversationQuotaReader.count_user_messages_today: "(self, user_id)",
            ConversationCleanupWriter.cleanup_stale_conversations: (
                "(self, *, stale_days=7, limit=5)"
            ),
        }
        for method, signature in expected.items():
            with self.subTest(method=method.__name__):
                self.assertEqual(str(_without_annotations(method)), signature)

    def test_attachment_table_crud_is_outside_boundary(self) -> None:
        public_methods = {
            name
            for capability in ConversationRepository.__mro__
            for name, value in capability.__dict__.items()
            if not name.startswith("_") and callable(value)
        }
        self.assertTrue(public_methods)
        self.assertFalse(any("attachment" in name for name in public_methods))


if __name__ == "__main__":
    unittest.main()
