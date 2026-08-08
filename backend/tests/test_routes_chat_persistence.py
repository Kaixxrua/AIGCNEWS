from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.app.api import routes_chat
from backend.app.api.dependencies import (
    get_conversation_repository,
    get_conversation_service,
    get_rag_chat_service,
)
from backend.app.core.auth import RequireUser
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
        stream_calls = []

        async def stream_chat(*args, **kwargs):
            stream_calls.append((args, kwargs))
            yield {"type": "sources", "data": [{"id": "source-1"}]}
            yield {"type": "thinking", "data": "thought"}
            yield {"type": "content", "data": "answer"}

        rag_service.stream_chat = stream_chat
        request = ChatStreamRequest(
            message=" question ",
            history=[{"role": "user", "content": "history"}],
            temperature=0.4,
            web_search=True,
        )

        conversation_service = MagicMock()
        conversation_service.append_message_pair = repository.append_message_pair

        async def collect():
            with patch.object(
                routes_chat.asyncio,
                "to_thread",
                new=AsyncMock(return_value=repository.append_message_pair.return_value),
            ) as to_thread:
                events = [
                    event
                    async for event in routes_chat._stream_persisted_chat(
                        request,
                        {"user_id": 3},
                        conversation_service=conversation_service,
                        rag_service=rag_service,
                    )
                ]
                return events, to_thread

        events, to_thread = asyncio.run(collect())

        self.assertEqual(
            events,
            [
                'data: {"type": "sources", "data": [{"id": "source-1"}]}\n\n',
                'data: {"type": "thinking", "data": "thought"}\n\n',
                'data: {"type": "content", "data": "answer"}\n\n',
                'data: {"type": "conversation", "data": {"conversation_id": 7, "message_id": 12}}\n\n',
                "data: [DONE]\n\n",
            ],
        )
        self.assertEqual(
            stream_calls,
            [
                (
                    ("question",),
                    {
                        "history": [{"role": "user", "content": "history"}],
                        "temperature": 0.4,
                        "web_search_enabled": True,
                    },
                )
            ],
        )
        to_thread.assert_awaited_once_with(
            conversation_service.append_message_pair,
            user_id=3,
            conversation_id=None,
            scope="global",
            scope_key=None,
            user_message="question",
            assistant_content="answer",
            assistant_thinking="thought",
            sources=[{"id": "source-1"}],
            attachments=[],
            title="question",
        )

    def test_cross_owner_attachment_is_ignored_without_changing_sse(self) -> None:
        persisted = {
            "conversation": {"id": 7},
            "assistant_message": {"id": 12},
        }
        rag_service = MagicMock()
        seen_messages: list[str] = []

        async def stream_chat(message, **kwargs):
            seen_messages.append(message)
            yield {"type": "content", "data": "answer"}

        rag_service.stream_chat = stream_chat
        request = ChatStreamRequest(
            message="question", history=[], attachment_ids=["other-owner"]
        )

        conversation_service = MagicMock()

        async def collect() -> list[str]:
            with (
                patch.object(
                    routes_chat.asyncio,
                    "to_thread",
                    new=AsyncMock(return_value=persisted),
                ),
                patch(
                    "backend.app.services.chat.attachment_service.get_attachment",
                    new=AsyncMock(return_value=None),
                ) as get_attachment,
            ):
                events = [
                    event
                    async for event in routes_chat._stream_persisted_chat(
                        request,
                        {"user_id": 3},
                        conversation_service=conversation_service,
                        rag_service=rag_service,
                    )
                ]
                get_attachment.assert_awaited_once_with("other-owner", 3)
                return events

        events = asyncio.run(collect())

        self.assertEqual(seen_messages, ["question"])
        self.assertEqual(events[0], 'data: {"type": "content", "data": "answer"}\n\n')
        self.assertIn('"type": "conversation"', events[-2])
        self.assertEqual(events[-1], "data: [DONE]\n\n")

    def test_ready_attachments_preserve_context_and_persisted_order(self) -> None:
        from backend.app.services.chat.attachment_service import (
            AttachmentMeta,
            AttachmentStatus,
            AttachmentType,
        )

        repository = MagicMock()
        persisted = {
            "conversation": {"id": 7},
            "assistant_message": {"id": 12},
        }
        rag_service = MagicMock()
        seen_messages: list[str] = []

        async def stream_chat(message, **kwargs):
            seen_messages.append(message)
            yield {"type": "content", "data": "answer"}

        rag_service.stream_chat = stream_chat
        metas = {
            "pdf": AttachmentMeta(
                id="pdf",
                user_id=3,
                type=AttachmentType.PDF,
                status=AttachmentStatus.READY,
                filename="report.pdf",
                page_count=4,
            ),
            "processing": AttachmentMeta(
                id="processing",
                user_id=3,
                type=AttachmentType.PDF,
                status=AttachmentStatus.PROCESSING,
            ),
            "image": AttachmentMeta(
                id="image",
                user_id=3,
                type=AttachmentType.IMAGE,
                status=AttachmentStatus.READY,
                filename="photo.png",
            ),
        }
        request = ChatStreamRequest(
            message="question",
            history=[],
            attachment_ids=["pdf", "processing", "missing", "image"],
        )

        conversation_service = MagicMock()
        conversation_service.append_message_pair = repository.append_message_pair

        async def collect() -> AsyncMock:
            with (
                patch.object(
                    routes_chat.asyncio,
                    "to_thread",
                    new=AsyncMock(return_value=persisted),
                ) as to_thread,
                patch(
                    "backend.app.services.chat.attachment_service.get_attachment",
                    new=AsyncMock(side_effect=lambda aid, user_id: metas.get(aid)),
                ),
                patch(
                    "backend.app.services.chat.attachment_service.get_pdf_text",
                    new=AsyncMock(return_value="x" * 9000),
                ) as get_pdf_text,
            ):
                _ = [
                    event
                    async for event in routes_chat._stream_persisted_chat(
                        request,
                        {"user_id": 3},
                        conversation_service=conversation_service,
                        rag_service=rag_service,
                    )
                ]
                get_pdf_text.assert_awaited_once_with("pdf", 3)
                return to_thread

        to_thread = asyncio.run(collect())

        self.assertIn("[用户上传的 PDF 文件: report.pdf]", seen_messages[0])
        self.assertIn("x" * 8000, seen_messages[0])
        self.assertNotIn("x" * 8001, seen_messages[0])
        self.assertIn("[PDF 内容结束，共 4 页]", seen_messages[0])
        self.assertIn("[用户上传了图片: photo.png", seen_messages[0])
        self.assertLess(seen_messages[0].index("report.pdf"), seen_messages[0].index("photo.png"))
        self.assertEqual(
            to_thread.await_args.kwargs["attachments"],
            [{"id": "pdf"}, {"id": "image"}],
        )

    def test_stream_error_still_emits_error_and_done(self) -> None:
        rag_service = MagicMock()

        async def stream_chat(*args, **kwargs):
            raise RuntimeError("upstream failed")
            yield

        rag_service.stream_chat = stream_chat
        request = ChatStreamRequest(message="question", history=[])
        conversation_service = MagicMock()

        async def collect() -> list[str]:
            return [
                event
                async for event in routes_chat._stream_persisted_chat(
                    request,
                    {"user_id": 3},
                    conversation_service=conversation_service,
                    rag_service=rag_service,
                )
            ]

        events = asyncio.run(collect())

        self.assertIn('"type": "error"', events[-2])
        self.assertEqual(events[-1], "data: [DONE]\n\n")


class ChatStreamRequestBoundaryTests(unittest.TestCase):
    def test_schema_accepts_boundary_lengths(self) -> None:
        request = ChatStreamRequest(
            message="x" * 16000,
            history=[{"role": "user", "content": "c"}] * 50,
            attachment_ids=[str(i) for i in range(10)],
        )

        self.assertEqual(len(request.message), 16000)
        self.assertEqual(len(request.history), 50)
        self.assertEqual(len(request.attachment_ids), 10)

    def test_schema_rejects_lengths_past_limits(self) -> None:
        with self.assertRaises(ValidationError):
            ChatStreamRequest(message="x" * 16001)
        with self.assertRaises(ValidationError):
            ChatStreamRequest(
                message="q", history=[{"role": "user", "content": "c"}] * 51
            )
        with self.assertRaises(ValidationError):
            ChatStreamRequest(
                message="q", attachment_ids=[str(i) for i in range(11)]
            )

    def test_stream_route_rejects_oversized_payload_with_422_before_model_work(
        self,
    ) -> None:
        app = FastAPI()
        app.include_router(routes_chat.router, prefix="/api")
        app.dependency_overrides[RequireUser] = lambda: {"user_id": 3, "role": "user"}
        quota_reader = MagicMock()
        app.dependency_overrides[get_conversation_repository] = lambda: quota_reader
        app.dependency_overrides[get_conversation_service] = MagicMock
        app.dependency_overrides[get_rag_chat_service] = MagicMock

        client = TestClient(app)
        responses = [
            client.post("/api/chat/stream", json={"message": "x" * 16001}),
            client.post(
                "/api/chat/stream",
                json={
                    "message": "q",
                    "history": [{"role": "user", "content": "c"}] * 51,
                },
            ),
            client.post(
                "/api/chat/stream",
                json={"message": "q", "attachment_ids": [str(i) for i in range(11)]},
            ),
        ]

        for response in responses:
            self.assertEqual(response.status_code, 422)
        # 校验失败在端点入口前拦截：不触发配额读取与后续模型编排
        quota_reader.count_user_messages_today.assert_not_called()


if __name__ == "__main__":
    unittest.main()
