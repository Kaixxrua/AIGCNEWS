from __future__ import annotations

import asyncio
import json
import unittest
from collections.abc import Iterable
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_vision
from backend.app.core.auth import RequireUser


class FakeProviderResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        lines: Iterable[str] = (),
        body: bytes = b"",
    ) -> None:
        self.status_code = status_code
        self._lines = list(lines)
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def aread(self) -> bytes:
        return self._body

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class FakeProviderClient:
    def __init__(self, provider: "FakeProvider", **kwargs) -> None:
        self.provider = provider
        self.provider.client_options.append(kwargs)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def stream(self, method: str, url: str, **kwargs):
        self.provider.requests.append((method, url, kwargs))
        outcome = self.provider.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeProvider:
    def __init__(self, outcomes: Iterable[FakeProviderResponse | BaseException]) -> None:
        self.outcomes = list(outcomes)
        self.client_options: list[dict] = []
        self.requests: list[tuple[str, str, dict]] = []

    def client_type(self, **kwargs):
        return FakeProviderClient(self, **kwargs)


def parse_sse(body: str) -> list[object]:
    events: list[object] = []
    for block in body.split("\n\n"):
        if not block:
            continue
        value = block.removeprefix("data: ")
        events.append(value if value == "[DONE]" else json.loads(value))
    return events


async def _collect_route_stream(stream) -> list[str]:
    return [chunk async for chunk in stream]


class VisionRelayContractsTests(unittest.TestCase):
    def setUp(self) -> None:
        routes_vision._image_cache._entries.clear()
        self.app = FastAPI()
        self.app.include_router(routes_vision.router, prefix="/api")

    def tearDown(self) -> None:
        routes_vision._image_cache._entries.clear()

    def authenticated_client(self, user: dict | None = None) -> TestClient:
        authenticated = user or {"user_id": 7}
        self.app.dependency_overrides[RequireUser] = lambda: authenticated
        return TestClient(self.app)

    def test_routes_require_auth_and_dependency_can_be_overridden(self) -> None:
        client = TestClient(self.app)
        upload = client.post(
            "/api/chat/upload-screenshot",
            json={"image_base64": "abcdefghij"},
        )
        relay = client.post(
            "/api/chat/vision-relay",
            json={"question": "q", "image_id": "missing"},
        )
        self.assertEqual(upload.status_code, 401)
        self.assertEqual(relay.status_code, 401)
        self.assertEqual(upload.json(), {"detail": "缺少 Authorization 头"})

        auth_calls: list[str] = []
        self.app.dependency_overrides[RequireUser] = lambda: auth_calls.append("auth") or {
            "user_id": 7
        }
        with patch.object(routes_vision._image_cache, "_id_factory", return_value="fixed-id"):
            response = TestClient(self.app).post(
                "/api/chat/upload-screenshot",
                json={"image_base64": "abcdefghij"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"image_id": "fixed-id"})
        self.assertEqual(auth_calls, ["auth"])
        openapi_paths = self.app.openapi()["paths"]
        self.assertEqual(
            set(openapi_paths["/api/chat/upload-screenshot"]),
            {"post"},
        )
        self.assertEqual(set(openapi_paths["/api/chat/vision-relay"]), {"post"})

    def test_request_validation_preserves_field_bounds_and_defaults(self) -> None:
        client = self.authenticated_client()
        invalid_uploads = [
            {},
            {"image_base64": "123456789"},
            {"image_base64": 42},
        ]
        for body in invalid_uploads:
            with self.subTest(upload=body):
                self.assertEqual(
                    client.post("/api/chat/upload-screenshot", json=body).status_code,
                    422,
                )

        invalid_relays = [
            {},
            {"question": "", "image_id": "id"},
            {"question": "q", "image_id": ""},
            {"question": "q" * 2001, "image_id": "id"},
            {"question": "q", "image_id": "id", "history": {}},
        ]
        for body in invalid_relays:
            with self.subTest(relay=body):
                self.assertEqual(
                    client.post("/api/chat/vision-relay", json=body).status_code,
                    422,
                )

        request = routes_vision.UploadScreenshotRequest(image_base64="abcdefghij")
        relay = routes_vision.VisionRelayRequest(question="q", image_id="id")
        self.assertEqual(request.mime_type, "image/jpeg")
        self.assertIsNone(relay.paper_id)
        self.assertEqual(relay.history, [])

    def test_upload_strips_data_uri_and_freezes_uuid_mime_ttl_and_write_eviction(self) -> None:
        routes_vision._image_cache._entries.update(
            {
                "expired": ("old", "image/gif", 199.999),
                "boundary": ("edge", "image/png", 200.0),
            }
        )
        with (
            patch.object(routes_vision._image_cache, "_id_factory", return_value="00000000-0000-0000-0000-000000000016"),
            patch.object(routes_vision._image_cache, "_clock", return_value=200.0),
        ):
            response = self.authenticated_client().post(
                "/api/chat/upload-screenshot",
                json={
                    "image_base64": "data:image/png;base64,encoded-image",
                    "mime_type": "image/webp",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"image_id": "00000000-0000-0000-0000-000000000016"},
        )
        self.assertNotIn("expired", routes_vision._image_cache._entries)
        self.assertEqual(
            routes_vision._image_cache._entries,
            {
                "boundary": ("edge", "image/png", 200.0),
                "00000000-0000-0000-0000-000000000016": (
                    "encoded-image",
                    "image/webp",
                    500.0,
                ),
            },
        )

    def test_read_expiry_boundary_and_expired_error_are_exact(self) -> None:
        routes_vision._image_cache._entries["boundary"] = ("image", "image/png", 100.0)
        provider = FakeProvider(
            [FakeProviderResponse(lines=["data: [DONE]"])]
        )
        with (
            patch.object(routes_vision._image_cache, "_clock", return_value=100.0),
            patch.object(routes_vision.httpx, "AsyncClient", provider.client_type),
        ):
            response = self.authenticated_client().post(
                "/api/chat/vision-relay",
                json={"question": "边界", "image_id": "boundary"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            parse_sse(response.text),
            [{"type": "status", "data": "🔍 正在分析图像内容…"}, "[DONE]"],
        )
        self.assertIn("boundary", routes_vision._image_cache._entries)

        routes_vision._image_cache._entries["expired"] = ("image", "image/png", 100.0)
        with patch.object(routes_vision._image_cache, "_clock", return_value=100.0001):
            expired = self.authenticated_client().post(
                "/api/chat/vision-relay",
                json={"question": "过期", "image_id": "expired"},
            )
        self.assertEqual(
            expired.content,
            (
                'data: {"type": "error", "data": '
                '"截图已过期或不存在，请重新截图后再提问"}\n\n'
                "data: [DONE]\n\n"
            ).encode(),
        )
        self.assertNotIn("expired", routes_vision._image_cache._entries)

    def test_provider_request_payload_history_system_model_key_and_url_are_exact(self) -> None:
        routes_vision._image_cache._entries["image-id"] = (
            "raw-base64",
            "image/webp",
            999.0,
        )
        history = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": index}
            for index in range(14)
        ]
        provider = FakeProvider(
            [
                FakeProviderResponse(
                    lines=[
                        "event: ignored",
                        "data: not-json",
                        'data: {"choices": []}',
                        'data: {"choices":[{"delta":{"content":"第一段"}}]}',
                        'data: {"choices":[{"delta":{"content":""}}]}',
                        'data: {"choices":[{"delta":{"content":"第二段"}}]}',
                        "data: [DONE]",
                        'data: {"choices":[{"delta":{"content":"never"}}]}',
                    ]
                )
            ]
        )
        with (
            patch.object(routes_vision._image_cache, "_clock", return_value=100.0),
            patch.object(routes_vision.settings, "siliconflow_api_key", "test-key"),
            patch.object(routes_vision.httpx, "AsyncClient", provider.client_type),
        ):
            response = self.authenticated_client().post(
                "/api/chat/vision-relay",
                json={
                    "paper_id": "paper-16",
                    "question": "解释截图",
                    "image_id": "image-id",
                    "history": history,
                },
            )

        self.assertEqual(provider.client_options, [{"timeout": 120.0}])
        method, url, kwargs = provider.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://api.siliconflow.cn/v1/chat/completions")
        self.assertEqual(
            kwargs["headers"],
            {"Authorization": "Bearer test-key", "Content-Type": "application/json"},
        )
        expected_messages = [
            {"role": "system", "content": routes_vision._VISION_SYSTEM},
            *[
                {
                    "role": "user" if index % 2 == 0 else "assistant",
                    "content": str(index),
                }
                for index in range(2, 14)
            ],
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:image/webp;base64,raw-base64"
                        },
                    },
                    {
                        "type": "text",
                        "text": "（当前论文 ID：paper-16）\n解释截图",
                    },
                ],
            },
        ]
        self.assertEqual(
            kwargs["json"],
            {
                "model": "Pro/moonshotai/Kimi-K2.5",
                "messages": expected_messages,
                "max_tokens": 4096,
                "temperature": 0.7,
                "stream": True,
            },
        )
        self.assertEqual(
            parse_sse(response.text),
            [
                {"type": "status", "data": "🔍 正在分析图像内容…"},
                {"type": "content", "data": "第一段"},
                {"type": "content", "data": "第二段"},
                "[DONE]",
            ],
        )
        self.assertEqual(response.text.count("data: [DONE]\n\n"), 1)

    def test_non_rate_failures_retry_twice_with_exponential_sleeps(self) -> None:
        routes_vision._image_cache._entries["image-id"] = ("image", "image/png", 999.0)
        provider = FakeProvider(
            [RuntimeError("provider busy"), RuntimeError("provider busy"), FakeProviderResponse()]
        )
        sleep = AsyncMock()
        with (
            patch.object(routes_vision._image_cache, "_clock", return_value=100.0),
            patch.object(routes_vision.httpx, "AsyncClient", provider.client_type),
            patch.object(routes_vision.asyncio, "sleep", sleep),
        ):
            response = self.authenticated_client().post(
                "/api/chat/vision-relay",
                json={"question": "q", "image_id": "image-id"},
            )

        self.assertEqual(len(provider.requests), 3)
        self.assertEqual(sleep.await_args_list[0].args, (2,))
        self.assertEqual(sleep.await_args_list[1].args, (4,))
        self.assertEqual(
            parse_sse(response.text),
            [
                {"type": "status", "data": "🔍 正在分析图像内容…"},
                {"type": "status", "data": "⏳ 模型繁忙，2s 后重试（第 1 次）…"},
                {"type": "status", "data": "⏳ 模型繁忙，4s 后重试（第 2 次）…"},
                "[DONE]",
            ],
        )

    def test_rate_limit_classification_retries_and_terminal_error_are_exact(self) -> None:
        routes_vision._image_cache._entries["image-id"] = ("image", "image/png", 999.0)
        provider = FakeProvider(
            [
                FakeProviderResponse(status_code=429, body=b"slow down"),
                RuntimeError("RATE LIMIT again"),
                FakeProviderResponse(status_code=503, body=b"unavailable\xff"),
            ]
        )
        sleep = AsyncMock()
        with (
            patch.object(routes_vision._image_cache, "_clock", return_value=100.0),
            patch.object(routes_vision.httpx, "AsyncClient", provider.client_type),
            patch.object(routes_vision.asyncio, "sleep", sleep),
            patch.object(routes_vision.traceback, "print_exc"),
        ):
            response = self.authenticated_client().post(
                "/api/chat/vision-relay",
                json={"question": "q", "image_id": "image-id"},
            )

        self.assertEqual(len(provider.requests), 3)
        self.assertEqual([call.args for call in sleep.await_args_list], [(30,), (60,)])
        self.assertEqual(
            parse_sse(response.text),
            [
                {"type": "status", "data": "🔍 正在分析图像内容…"},
                {"type": "status", "data": "⏳ 触发限速，30s 后重试（第 1 次）…"},
                {"type": "status", "data": "⏳ 触发限速，60s 后重试（第 2 次）…"},
                {
                    "type": "error",
                    "data": "视觉分析失败：Error code: 503 - unavailable�",
                },
                "[DONE]",
            ],
        )
        self.assertEqual(response.text.count("data: [DONE]\n\n"), 1)

    def test_private_stream_forwards_request_and_legacy_seams_to_relay(self) -> None:
        request = routes_vision.VisionRelayRequest(
            paper_id="paper-18",
            question="explain",
            image_id="image-id",
            history=[{"role": "user", "content": "before"}],
        )
        captured: dict = {}

        async def relay_stream(**kwargs):
            captured.update(kwargs)
            yield "relay-chunk"

        with patch.object(
            routes_vision.vision_relay_service,
            "stream_vision_relay",
            relay_stream,
        ):
            chunks = asyncio.run(
                _collect_route_stream(routes_vision._vision_relay_stream(request))
            )

        self.assertEqual(chunks, ["relay-chunk"])
        self.assertEqual(captured["image_id"], "image-id")
        self.assertEqual(captured["question"], "explain")
        self.assertEqual(captured["paper_id"], "paper-18")
        self.assertEqual(captured["history"], request.history)
        self.assertIs(captured["encode_event"], routes_vision._sse)
        self.assertIs(captured["report_error"], routes_vision.traceback.print_exc)
        self.assertTrue(callable(captured["image_loader"]))
        self.assertTrue(callable(captured["provider_stream"]))

    def test_streaming_response_headers_content_type_and_exact_bytes(self) -> None:
        routes_vision._image_cache._entries["image-id"] = ("image", "image/png", 999.0)
        provider = FakeProvider(
            [
                FakeProviderResponse(
                    lines=['data: {"choices":[{"delta":{"content":"字节"}}]}']
                )
            ]
        )
        with (
            patch.object(routes_vision._image_cache, "_clock", return_value=100.0),
            patch.object(routes_vision.httpx, "AsyncClient", provider.client_type),
        ):
            response = self.authenticated_client().post(
                "/api/chat/vision-relay",
                json={"question": "q", "image_id": "image-id"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/event-stream; charset=utf-8")
        self.assertEqual(response.headers["cache-control"], "no-cache, no-transform")
        self.assertEqual(response.headers["connection"], "keep-alive")
        self.assertEqual(response.headers["x-accel-buffering"], "no")
        self.assertEqual(response.headers["content-encoding"], "identity")
        self.assertEqual(
            response.content,
            (
                'data: {"type": "status", "data": "🔍 正在分析图像内容…"}\n\n'
                'data: {"type": "content", "data": "字节"}\n\n'
                "data: [DONE]\n\n"
            ).encode("utf-8"),
        )
        self.assertEqual(response.content.count(b"data: [DONE]\n\n"), 1)


if __name__ == "__main__":
    unittest.main()
