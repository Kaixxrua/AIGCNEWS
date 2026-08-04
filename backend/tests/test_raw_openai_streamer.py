"""raw_openai_streamer：OpenAI 兼容 SSE 流式 / 非流式客户端契约测试。

httpx.AsyncClient 整体替换为替身，验证：
  - SSE 跨 chunk 缓冲解析、[DONE] 终止、坏行容错
  - reasoning_content / content 增量的正确拆分
  - 请求 URL / payload / headers 形状与 settings 默认值回退
  - 非流式 tool_calls / reasoning / finish_reason 解析
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from backend.app.services.rag import raw_openai_streamer
from backend.app.services.rag.raw_openai_streamer import (
    ChatCompletionResult,
    StreamDelta,
    chat_completions,
    stream_chat_completions,
)


class _FakeStreamResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def raise_for_status(self) -> None:
        return None

    async def aiter_bytes(self):  # noqa: ANN202 — 与 httpx 响应保持同形
        for chunk in self._chunks:
            yield chunk


class _FakeStreamContext:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeStreamResponse:
        return self._response

    async def __aexit__(self, *exc: Any) -> bool:
        return False


class _FakePostResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def _make_fake_client(
    *,
    stream_chunks: list[bytes] | None = None,
    post_payload: dict[str, Any] | None = None,
) -> type:
    """构造记录请求参数并回放预设响应的 httpx.AsyncClient 替身类。"""

    class FakeAsyncClient:
        requests: list[dict[str, Any]] = []

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.timeout = kwargs.get("timeout")

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            return False

        def stream(self, method: str, url: str, *, json: Any = None, headers: Any = None) -> _FakeStreamContext:
            self.requests.append({"method": method, "url": url, "json": json, "headers": headers})
            return _FakeStreamContext(_FakeStreamResponse(stream_chunks or []))

        async def post(self, url: str, *, json: Any = None, headers: Any = None) -> _FakePostResponse:
            self.requests.append({"method": "POST", "url": url, "json": json, "headers": headers})
            return _FakePostResponse(post_payload or {})

    return FakeAsyncClient


class StreamChatCompletionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_parses_deltas_across_chunk_boundaries_and_stops_at_done(self) -> None:
        chunks = [
            b'data: {"choices":[{"delta":{"reasoning_content":"think-"}}]}\n\n'
            b': ping\n\n'
            b'data: {bad json}\n\n'
            b'data: {"choices":[{"delta":{}}]}\n\n'
            b'data: {"choices":[{"delta":{"content":"Hel',
            b'lo"}}]}\n\n'
            b'data: [DONE]\n\n'
            b'data: {"choices":[{"delta":{"content":"after-done"}}]}\n\n',
        ]
        fake = _make_fake_client(stream_chunks=chunks)
        with patch.object(raw_openai_streamer.httpx, "AsyncClient", fake):
            deltas = [
                delta
                async for delta in stream_chat_completions(
                    messages=[{"role": "user", "content": "hi"}],
                    model="demo-model",
                    api_key="secret",
                    base_url="https://api.example.com",
                )
            ]
        assert deltas == [
            StreamDelta(reasoning="think-", content=""),
            StreamDelta(reasoning="", content="Hello"),
        ]

    async def test_stream_request_shape(self) -> None:
        fake = _make_fake_client(stream_chunks=[b"data: [DONE]\n\n"])
        messages = [{"role": "user", "content": "hi"}]
        with patch.object(raw_openai_streamer.httpx, "AsyncClient", fake):
            async for _ in stream_chat_completions(
                messages=messages,
                model="demo-model",
                api_key="secret",
                base_url="https://api.example.com/",
                temperature=0.2,
                max_tokens=128,
            ):
                pass
        request = fake.requests[0]
        assert request["method"] == "POST"
        assert request["url"] == "https://api.example.com/chat/completions"
        assert request["json"] == {
            "model": "demo-model",
            "messages": messages,
            "stream": True,
            "temperature": 0.2,
            "max_tokens": 128,
        }
        assert request["headers"]["Authorization"] == "Bearer secret"
        assert request["headers"]["Accept"] == "text/event-stream"

    async def test_defaults_fall_back_to_settings(self) -> None:
        fake = _make_fake_client(stream_chunks=[b"data: [DONE]\n\n"])
        with (
            patch.object(raw_openai_streamer.httpx, "AsyncClient", fake),
            patch.object(raw_openai_streamer.settings, "chat_model_name", "cfg-model"),
            patch.object(raw_openai_streamer.settings, "openai_api_key", "cfg-key"),
            patch.object(raw_openai_streamer.settings, "openai_base_url", "https://cfg.example.com/v1/"),
        ):
            async for _ in stream_chat_completions(messages=[]):
                pass
        request = fake.requests[0]
        assert request["url"] == "https://cfg.example.com/v1/chat/completions"
        assert request["json"]["model"] == "cfg-model"
        assert request["headers"]["Authorization"] == "Bearer cfg-key"


class ChatCompletionsTests(unittest.IsolatedAsyncioTestCase):
    async def test_parses_tool_calls_reasoning_and_finish_reason(self) -> None:
        payload = {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": "",
                        "reasoning_content": "need tool",
                        "tool_calls": [
                            {"id": "call_1", "function": {"name": "search", "arguments": '{"q":"x"}'}},
                            {"id": "call_2", "function": {"name": "lookup"}},
                        ],
                    },
                }
            ]
        }
        fake = _make_fake_client(post_payload=payload)
        tools = [{"type": "function", "function": {"name": "search"}}]
        with patch.object(raw_openai_streamer.httpx, "AsyncClient", fake):
            result = await chat_completions(
                messages=[{"role": "user", "content": "hi"}],
                model="demo-model",
                api_key="secret",
                base_url="https://api.example.com",
                tools=tools,
                tool_choice="auto",
            )
        assert result.finish_reason == "tool_calls"
        assert result.reasoning == "need tool"
        assert [(tc.id, tc.name, tc.arguments) for tc in result.tool_calls] == [
            ("call_1", "search", '{"q":"x"}'),
            ("call_2", "lookup", "{}"),
        ]
        request = fake.requests[0]
        assert request["json"]["stream"] is False
        assert request["json"]["tools"] == tools
        assert request["json"]["tool_choice"] == "auto"

    async def test_tools_omitted_when_not_provided(self) -> None:
        payload = {"choices": [{"finish_reason": "stop", "message": {"content": "hi"}}]}
        fake = _make_fake_client(post_payload=payload)
        with patch.object(raw_openai_streamer.httpx, "AsyncClient", fake):
            result = await chat_completions(
                messages=[],
                model="demo-model",
                api_key="secret",
                base_url="https://api.example.com",
            )
        assert result.content == "hi"
        assert result.finish_reason == "stop"
        assert result.tool_calls == []
        request = fake.requests[0]
        assert "tools" not in request["json"]
        assert "tool_choice" not in request["json"]

    async def test_empty_choices_returns_default_result(self) -> None:
        fake = _make_fake_client(post_payload={"choices": []})
        with patch.object(raw_openai_streamer.httpx, "AsyncClient", fake):
            result = await chat_completions(
                messages=[],
                model="demo-model",
                api_key="secret",
                base_url="https://api.example.com",
            )
        assert result == ChatCompletionResult()
