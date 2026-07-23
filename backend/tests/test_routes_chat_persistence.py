from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from backend.app.api import routes_chat
from backend.app.models.schema_chat import ChatStreamRequest


class ChatPersistenceRouteTests(unittest.TestCase):
    def test_quota_uses_injected_reader_before_model_work(self) -> None:
        reader = MagicMock()
        reader.count_user_messages_today.return_value = 20

        with patch.object(routes_chat.settings, "USER_DAILY_MESSAGE_LIMIT", 20):
            with self.assertRaises(HTTPException) as raised:
                routes_chat._check_user_message_limit(
                    {"user_id": 3, "role": "user"},
                    reader,
                )

        self.assertEqual(raised.exception.status_code, 429)
        self.assertEqual(raised.exception.detail["error"], "message_limit_exceeded")
        self.assertEqual(raised.exception.detail["used"], 20)
        reader.count_user_messages_today.assert_called_once_with(3)

    def test_stream_preserves_conversation_event_and_terminal_done(self) -> None:
        repository = MagicMock()
        repository.append_message_pair.return_value = {
            "conversation": {"id": 7},
            "assistant_message": {"id": 12},
        }
        rag_service = MagicMock()

        async def stream_chat(*args, **kwargs):
            yield {"type": "content", "data": "answer"}

        rag_service.stream_chat = stream_chat
        request = ChatStreamRequest(message="question", history=[])

        async def collect() -> list[str]:
            with (
                patch.object(routes_chat, "HybridRetriever", return_value=MagicMock()),
                patch.object(routes_chat, "ChatService", return_value=rag_service),
                patch.object(routes_chat, "ConversationService") as service_type,
                patch.object(
                    routes_chat.asyncio,
                    "to_thread",
                    new=AsyncMock(return_value=repository.append_message_pair.return_value),
                ),
            ):
                service_type.return_value.append_message_pair = repository.append_message_pair
                return [
                    event
                    async for event in routes_chat._stream_persisted_chat(
                        request,
                        {"user_id": 3},
                        conversation_repository=repository,
                    )
                ]

        events = asyncio.run(collect())

        self.assertEqual(events[0], 'data: {"type": "content", "data": "answer"}\n\n')
        self.assertIn('"type": "conversation"', events[-2])
        self.assertIn('"conversation_id": 7', events[-2])
        self.assertIn('"message_id": 12', events[-2])
        self.assertEqual(events[-1], "data: [DONE]\n\n")

    def test_stream_error_still_emits_error_and_done(self) -> None:
        rag_service = MagicMock()

        async def stream_chat(*args, **kwargs):
            raise RuntimeError("upstream failed")
            yield

        rag_service.stream_chat = stream_chat
        request = ChatStreamRequest(message="question", history=[])

        async def collect() -> list[str]:
            with (
                patch.object(routes_chat, "HybridRetriever", return_value=MagicMock()),
                patch.object(routes_chat, "ChatService", return_value=rag_service),
            ):
                return [
                    event
                    async for event in routes_chat._stream_persisted_chat(
                        request,
                        {"user_id": 3},
                        conversation_repository=MagicMock(),
                    )
                ]

        events = asyncio.run(collect())

        self.assertIn('"type": "error"', events[-2])
        self.assertEqual(events[-1], "data: [DONE]\n\n")


if __name__ == "__main__":
    unittest.main()
