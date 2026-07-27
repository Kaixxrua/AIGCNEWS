"""SiliconFlow Vision provider streaming transport boundary."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

VISION_BASE_URL = "https://api.siliconflow.cn/v1"
VISION_MODEL = "Pro/moonshotai/Kimi-K2.5"
VISION_TIMEOUT_SECONDS = 120.0
VISION_SYSTEM = (
    "你是一位顶级 AI 研究员，擅长深度解读学术论文中的图表、公式、文字与实验结果。"
    "你将直接看到用户截取的论文区域图片，并结合用户的追问给出有见地的深度分析回答。"
    "回答要简洁有力，直接切中要点。"
)


@dataclass(frozen=True)
class ProviderEvent:
    type: str
    data: str


class VisionProvider:
    """Build and stream the current SiliconFlow Vision request."""

    def __init__(
        self,
        *,
        api_key: str,
        client_factory: Callable[..., Any] = httpx.AsyncClient,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self._api_key = api_key
        self._client_factory = client_factory
        self._sleep = sleep

    async def stream(
        self,
        *,
        data_uri: str,
        question: str,
        paper_id: str | None = None,
        history: Iterable[Mapping[str, Any]] = (),
    ) -> AsyncGenerator[ProviderEvent, None]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": VISION_SYSTEM},
        ]
        history_items = list(history)
        for item in history_items[-12:]:
            if (
                isinstance(item, dict)
                and item.get("role")
                and item.get("content")
            ):
                messages.append(
                    {"role": item["role"], "content": str(item["content"])}
                )

        user_text = question
        if paper_id:
            user_text = f"（当前论文 ID：{paper_id}）\n{user_text}"
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": data_uri},
                    },
                    {
                        "type": "text",
                        "text": user_text,
                    },
                ],
            }
        )

        payload = {
            "model": VISION_MODEL,
            "messages": messages,
            "max_tokens": 4096,
            "temperature": 0.7,
            "stream": True,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(3):
            try:
                async with self._client_factory(
                    timeout=VISION_TIMEOUT_SECONDS
                ) as client:
                    async with client.stream(
                        "POST",
                        f"{VISION_BASE_URL}/chat/completions",
                        json=payload,
                        headers=headers,
                    ) as response:
                        if response.status_code != 200:
                            body = await response.aread()
                            error_text = body.decode("utf-8", errors="replace")
                            if response.status_code == 429:
                                raise Exception(f"429 rate limit: {error_text}")
                            raise Exception(
                                f"Error code: {response.status_code} - {error_text}"
                            )

                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data_string = line[5:].strip()
                            if data_string == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_string)
                                choices = chunk.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content")
                                    if content:
                                        yield ProviderEvent("content", content)
                            except json.JSONDecodeError:
                                continue
                break
            except Exception as exc:
                if attempt == 2:
                    raise
                error_string = str(exc)
                is_rate_limit = (
                    "429" in error_string
                    or "rate_limit" in error_string
                    or "rate limit" in error_string.lower()
                )
                wait = 30 * (attempt + 1) if is_rate_limit else 2 ** (attempt + 1)
                yield ProviderEvent(
                    "status",
                    f"⏳ {'触发限速，' if is_rate_limit else '模型繁忙，'}"
                    f"{wait}s 后重试（第 {attempt + 1} 次）…",
                )
                await self._sleep(wait)
