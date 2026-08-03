from __future__ import annotations

import asyncio
import unittest
from collections.abc import Iterable
from unittest.mock import AsyncMock

from backend.app.services.vision.provider import (
    VISION_SYSTEM,
    ProviderEvent,
    VisionProvider,
)


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
    def __init__(self, provider: "FakeHttpx", **kwargs) -> None:
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


class FakeHttpx:
    def __init__(self, outcomes: Iterable[FakeProviderResponse | BaseException]) -> None:
        self.outcomes = list(outcomes)
        self.client_options: list[dict] = []
        self.requests: list[tuple[str, str, dict]] = []

    def client_factory(self, **kwargs):
        return FakeProviderClient(self, **kwargs)


async def collect(provider: VisionProvider, **kwargs) -> list[ProviderEvent]:
    return [event async for event in provider.stream(**kwargs)]


class VisionProviderTests(unittest.TestCase):
    def test_request_timeout_url_key_model_history_and_lines_are_exact(self) -> None:
        httpx = FakeHttpx(
            [
                FakeProviderResponse(
                    lines=[
                        "event: ignored",
                        " data: ignored-leading-space",
                        "data: not-json",
                        'data: {"choices":[]}',
                        'data: {"choices":[{"delta":{"content":"第一段"}}]}',
                        'data: {"choices":[{"delta":{"content":""}}]}',
                        "data: [DONE]",
                        'data: {"choices":[{"delta":{"content":"never"}}]}',
                    ]
                )
            ]
        )
        history = [
            {"role": "user" if index % 2 == 0 else "assistant", "content": index}
            for index in range(14)
        ]
        provider = VisionProvider(
            api_key="test-key",
            client_factory=httpx.client_factory,
        )

        events = asyncio.run(
            collect(
                provider,
                data_uri="data:image/webp;base64,raw-base64",
                question="解释截图",
                paper_id="paper-17",
                history=history,
            )
        )

        self.assertEqual(httpx.client_options, [{"timeout": 120.0}])
        method, url, kwargs = httpx.requests[0]
        self.assertEqual(method, "POST")
        self.assertEqual(url, "https://api.siliconflow.cn/v1/chat/completions")
        self.assertEqual(
            kwargs["headers"],
            {"Authorization": "Bearer test-key", "Content-Type": "application/json"},
        )
        self.assertEqual(
            kwargs["json"],
            {
                "model": "Pro/moonshotai/Kimi-K2.5",
                "messages": [
                    {"role": "system", "content": VISION_SYSTEM},
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
                                "text": "（当前论文 ID：paper-17）\n解释截图",
                            },
                        ],
                    },
                ],
                "max_tokens": 4096,
                "temperature": 0.7,
                "stream": True,
            },
        )
        self.assertEqual(events, [ProviderEvent("content", "第一段")])

    def test_non_rate_failures_retry_with_exact_statuses_and_sleeps(self) -> None:
        httpx = FakeHttpx(
            [RuntimeError("provider busy"), RuntimeError("provider busy"), FakeProviderResponse()]
        )
        sleep = AsyncMock()
        provider = VisionProvider(
            api_key="key",
            client_factory=httpx.client_factory,
            sleep=sleep,
        )

        events = asyncio.run(
            collect(provider, data_uri="data:image/png;base64,image", question="q")
        )

        self.assertEqual(len(httpx.requests), 3)
        self.assertEqual([call.args for call in sleep.await_args_list], [(2,), (4,)])
        self.assertEqual(
            events,
            [
                ProviderEvent("status", "⏳ 模型繁忙，2s 后重试（第 1 次）…"),
                ProviderEvent("status", "⏳ 模型繁忙，4s 后重试（第 2 次）…"),
            ],
        )

    def test_status_body_decoding_rate_limit_and_terminal_error_are_exact(self) -> None:
        httpx = FakeHttpx(
            [
                FakeProviderResponse(status_code=429, body=b"slow down"),
                RuntimeError("RATE LIMIT again"),
                FakeProviderResponse(status_code=503, body=b"unavailable\xff"),
            ]
        )
        sleep = AsyncMock()
        provider = VisionProvider(
            api_key="key",
            client_factory=httpx.client_factory,
            sleep=sleep,
        )

        async def run() -> tuple[list[ProviderEvent], Exception | None]:
            events: list[ProviderEvent] = []
            try:
                async for event in provider.stream(
                    data_uri="data:image/png;base64,image",
                    question="q",
                ):
                    events.append(event)
            except Exception as exc:
                return events, exc
            return events, None

        events, error = asyncio.run(run())

        self.assertEqual([call.args for call in sleep.await_args_list], [(30,), (60,)])
        self.assertEqual(
            events,
            [
                ProviderEvent("status", "⏳ 触发限速，30s 后重试（第 1 次）…"),
                ProviderEvent("status", "⏳ 触发限速，60s 后重试（第 2 次）…"),
            ],
        )
        self.assertIsNotNone(error)
        self.assertEqual(str(error), "Error code: 503 - unavailable�")


if __name__ == "__main__":
    unittest.main()
