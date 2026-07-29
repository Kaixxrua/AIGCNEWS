from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.app.repositories.conversation_repository import ConversationRepository
from backend.app.services.chat.conversation_service import ConversationService


class ConversationServiceTests(unittest.TestCase):
    def test_append_pair_delegates_atomic_operation_with_retention(self) -> None:
        repository = MagicMock(spec=ConversationRepository)
        repository.append_message_pair.return_value = {"conversation": {"id": 7}}
        service = ConversationService(
            repository,
            max_messages=12,
            max_conversations=8,
        )

        result = service.append_message_pair(
            user_id=3,
            conversation_id=7,
            scope="global",
            scope_key=None,
            user_message="  first line\nsecond line  ",
            assistant_content="answer",
        )

        self.assertEqual(result, {"conversation": {"id": 7}})
        repository.append_message_pair.assert_called_once_with(
            user_id=3,
            conversation_id=7,
            scope="global",
            scope_key=None,
            user_message="  first line\nsecond line  ",
            assistant_content="answer",
            assistant_thinking="",
            sources=None,
            attachments=None,
            parent_message_id=None,
            title="first line second line",
            max_messages=12,
            max_conversations=8,
        )

    def test_missing_owned_context_preserves_error(self) -> None:
        repository = MagicMock(spec=ConversationRepository)
        repository.get_owned_conversation_context.return_value = None
        service = ConversationService(repository)

        with self.assertRaisesRegex(ValueError, "conversation_not_found"):
            service.get_conversation_context(user_id=3, conversation_id=99)

    def test_missing_owned_message_preserves_error(self) -> None:
        repository = MagicMock(spec=ConversationRepository)
        repository.delete_owned_message_branch.return_value = None
        service = ConversationService(repository)

        with self.assertRaisesRegex(ValueError, "message_not_found"):
            service.delete_message(user_id=3, message_id=99)

    def test_visual_regeneration_is_rejected_before_destructive_prepare(self) -> None:
        repository = MagicMock(spec=ConversationRepository)
        repository.get_owned_message_regeneration_preflight.return_value = {
            "id": 9,
            "attachments": [{"modality": "vision"}],
        }
        service = ConversationService(repository)

        with self.assertRaisesRegex(
            ValueError, "visual_message_regeneration_not_supported"
        ):
            service.regenerate_from_message(user_id=3, message_id=9)

        repository.prepare_owned_regeneration.assert_not_called()

    def test_cleanup_preserves_configured_bounds(self) -> None:
        repository = MagicMock(spec=ConversationRepository)
        repository.cleanup_stale_conversations.return_value = 4
        service = ConversationService(
            repository,
            cleanup_stale_days=9,
            cleanup_batch_size=4,
        )

        self.assertEqual(service.cleanup_stale_conversations(), 4)
        repository.cleanup_stale_conversations.assert_called_once_with(
            stale_days=9,
            limit=4,
        )


if __name__ == "__main__":
    unittest.main()
