from __future__ import annotations

import asyncio
import unittest
from unittest.mock import Mock

from backend.app.services.vision.provider import ProviderEvent
from backend.app.services.vision.relay import DONE_EVENT, encode_sse, stream_vision_relay


async def collect(**kwargs) -> list[str]:
    return [chunk async for chunk in stream_vision_relay(**kwargs)]


class VisionRelayTests(unittest.TestCase):
    def test_sse_encoding_is_exact_for_unicode_and_json_escaping(self) -> None:
        self.assertEqual(
            encode_sse("content", '中文 "quoted"\nnext'),
            'data: {"type": "content", "data": "中文 \\"quoted\\"\\nnext"}\n\n',
        )

    def test_missing_image_emits_exact_error_and_done_without_provider_call(self) -> None:
        provider_stream = Mock()

        async def load_image(_image_id: str):
            return None

        chunks = asyncio.run(
            collect(
                image_id="missing",
                question="q",
                paper_id=None,
                history=[],
                image_loader=load_image,
                provider_stream=provider_stream,
            )
        )

        self.assertEqual(
            chunks,
            [
                'data: {"type": "error", "data": "截图已过期或不存在，请重新截图后再提问"}\n\n',
                DONE_EVENT,
            ],
        )
        provider_stream.assert_not_called()

    def test_provider_retry_and_content_events_are_encoded_in_order(self) -> None:
        history = [{"role": "user", "content": "before"}]
        calls: list[dict] = []

        async def load_image(image_id: str):
            self.assertEqual(image_id, "image-id")
            return "raw-base64", "image/webp"

        async def provider_stream(**kwargs):
            calls.append(kwargs)
            yield ProviderEvent("status", "retry")
            yield ProviderEvent("content", "answer")

        chunks = asyncio.run(
            collect(
                image_id="image-id",
                question="explain",
                paper_id="paper-18",
                history=history,
                image_loader=load_image,
                provider_stream=provider_stream,
            )
        )

        self.assertEqual(
            calls,
            [
                {
                    "data_uri": "data:image/webp;base64,raw-base64",
                    "question": "explain",
                    "paper_id": "paper-18",
                    "history": history,
                }
            ],
        )
        self.assertEqual(
            chunks,
            [
                'data: {"type": "status", "data": "🔍 正在分析图像内容…"}\n\n',
                'data: {"type": "status", "data": "retry"}\n\n',
                'data: {"type": "content", "data": "answer"}\n\n',
                DONE_EVENT,
            ],
        )

    def test_success_persists_answer_and_emits_conversation_before_done(self) -> None:
        persisted_answers: list[str] = []

        async def load_image(_image_id: str):
            return "image", "image/png"

        async def provider_stream(**_kwargs):
            yield ProviderEvent("content", "first")
            yield ProviderEvent("content", " second")

        async def persist_completed(answer: str):
            persisted_answers.append(answer)
            return {
                "conversation": {"id": 7},
                "assistant_message": {"id": 12},
            }

        chunks = asyncio.run(
            collect(
                image_id="image-id",
                question="q",
                paper_id=None,
                history=[],
                image_loader=load_image,
                provider_stream=provider_stream,
                persist_completed=persist_completed,
            )
        )

        self.assertEqual(persisted_answers, ["first second"])
        self.assertEqual(
            chunks[-2:],
            [
                'data: {"type": "conversation", "data": {"conversation_id": 7, "message_id": 12}}\n\n',
                DONE_EVENT,
            ],
        )

    def test_terminal_provider_error_reports_and_emits_one_done(self) -> None:
        report_error = Mock()

        async def load_image(_image_id: str):
            return "image", "image/png"

        async def provider_stream(**_kwargs):
            if False:
                yield ProviderEvent("content", "never")
            raise RuntimeError("provider failed")

        chunks = asyncio.run(
            collect(
                image_id="image-id",
                question="q",
                paper_id=None,
                history=[],
                image_loader=load_image,
                provider_stream=provider_stream,
                report_error=report_error,
            )
        )

        report_error.assert_called_once_with()
        self.assertEqual(
            chunks,
            [
                'data: {"type": "status", "data": "🔍 正在分析图像内容…"}\n\n',
                'data: {"type": "error", "data": "视觉分析失败：provider failed"}\n\n',
                DONE_EVENT,
            ],
        )
        self.assertEqual(chunks.count(DONE_EVENT), 1)


if __name__ == "__main__":
    unittest.main()
