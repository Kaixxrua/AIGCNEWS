"""Vision message relay coordination and exact SSE event encoding."""

from __future__ import annotations

import asyncio
import json
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    Awaitable,
    Callable,
    Iterable,
    Mapping,
)
from typing import Any

from backend.app.services.vision.provider import ProviderEvent

ANALYZING_STATUS = "🔍 正在分析图像内容…"
MISSING_IMAGE_ERROR = "截图已过期或不存在，请重新截图后再提问"
DONE_EVENT = "data: [DONE]\n\n"

ImagePayload = tuple[str, str]
ImageLoader = Callable[[str], Awaitable[ImagePayload | None]]
ProviderStream = Callable[..., AsyncIterable[ProviderEvent]]
EventEncoder = Callable[[str, Any], str]
ErrorReporter = Callable[[], None]
CompletedPersister = Callable[[str], Awaitable[Mapping[str, Any]]]


def encode_sse(event_type: str, data: Any) -> str:
    """Encode one relay event using the route's frozen SSE byte format."""
    payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


async def stream_vision_relay(
    *,
    image_id: str,
    question: str,
    paper_id: str | None,
    history: Iterable[Mapping[str, Any]],
    image_loader: ImageLoader,
    provider_stream: ProviderStream,
    encode_event: EventEncoder = encode_sse,
    report_error: ErrorReporter | None = None,
    persist_completed: CompletedPersister | None = None,
) -> AsyncGenerator[str, None]:
    """Coordinate cached-image lookup and provider events into route SSE chunks."""
    image = await image_loader(image_id)
    if image is None:
        yield encode_event("error", MISSING_IMAGE_ERROR)
        yield DONE_EVENT
        return

    base64_data, mime_type = image
    data_uri = f"data:{mime_type};base64,{base64_data}"

    content_parts: list[str] = []
    cancelled = False
    try:
        yield encode_event("status", ANALYZING_STATUS)
        async for event in provider_stream(
            data_uri=data_uri,
            question=question,
            paper_id=paper_id,
            history=history,
        ):
            if event.type == "content" and event.data:
                content_parts.append(event.data)
            yield encode_event(event.type, event.data)
        answer = "".join(content_parts)
        if persist_completed is not None and answer.strip():
            persisted = await persist_completed(answer)
            yield encode_event(
                "conversation",
                {
                    "conversation_id": persisted["conversation"]["id"],
                    "message_id": persisted["assistant_message"]["id"],
                },
            )
    except asyncio.CancelledError:
        cancelled = True
        raise
    except Exception as exc:
        if report_error is not None:
            report_error()
        yield encode_event("error", f"视觉分析失败：{exc}")
    finally:
        if not cancelled:
            yield DONE_EVENT
