"""
直接调用 OpenAI 兼容 API 的流式 / 非流式客户端。

LangChain 的 ChatOpenAI._convert_delta_to_message_chunk 会丢弃
第三方扩展字段（如硅基流动 DeepSeek-R1 返回的 reasoning_content），
导致思维链永远为空。

本模块绕过 LangChain，用 httpx 直接请求 /v1/chat/completions，
自行解析 SSE 事件，正确提取 reasoning_content（思维链）和 content（正文）。

同时提供非流式 ``chat_completions()`` 用于 Function Calling / Tool Use 场景——
第一轮调用带 tools 让 LLM 判断是否需要调用工具，该轮不需要流式输出。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx

from backend.app.core.config import settings


@dataclass
class StreamDelta:
    """一个流式增量片段。"""

    reasoning: str  # 思维链增量（可为空）
    content: str  # 正文增量（可为空）


@dataclass
class ToolCallResult:
    """LLM 返回的单个工具调用。"""

    id: str  # tool_call id，回传时需要
    name: str  # 工具函数名
    arguments: str  # JSON 字符串形式的参数


@dataclass
class ChatCompletionResult:
    """非流式调用返回结果。"""

    content: str = ""
    reasoning: str = ""
    tool_calls: List[ToolCallResult] = field(default_factory=list)
    finish_reason: str = ""


async def stream_chat_completions(
    *,
    messages: List[Dict[str, str]],
    model: Optional[str] = None,
    temperature: float = 0.6,
    max_tokens: int = 8192,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> AsyncGenerator[StreamDelta, None]:
    """
    流式调用 OpenAI 兼容 /v1/chat/completions 接口。

    逐 SSE 事件 yield StreamDelta，调用方可实时获取 reasoning + content。

    Parameters
    ----------
    messages : 对话消息列表，格式 [{"role": "user", "content": "..."}]
    model    : 模型名称，默认取 settings.chat_model_name
    temperature : 采样温度
    max_tokens  : 最大输出 token 数
    api_key  : API Key，默认取 settings.openai_api_key
    base_url : API 端点，默认取 settings.openai_base_url
    """
    effective_model = model or settings.chat_model_name
    effective_key = api_key or settings.openai_api_key
    effective_base = (base_url or settings.openai_base_url or "").rstrip("/")
    url = f"{effective_base}/chat/completions"

    payload = {
        "model": effective_model,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    headers = {
        "Authorization": f"Bearer {effective_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()

            buffer = ""
            async for raw_bytes in resp.aiter_bytes():
                buffer += raw_bytes.decode("utf-8", errors="replace")

                # SSE 事件以两个换行符分隔
                while "\n\n" in buffer:
                    event_str, buffer = buffer.split("\n\n", 1)

                    for line in event_str.split("\n"):
                        line = line.strip()
                        if not line.startswith("data:"):
                            continue
                        data_str = line[len("data:") :].strip()
                        if data_str == "[DONE]":
                            return

                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        choices = data.get("choices") or []
                        if not choices:
                            continue

                        delta = choices[0].get("delta") or {}
                        reasoning = delta.get("reasoning_content") or ""
                        content = delta.get("content") or ""

                        if reasoning or content:
                            yield StreamDelta(reasoning=reasoning, content=content)


async def chat_completions(
    *,
    messages: List[Dict[str, Any]],
    model: Optional[str] = None,
    temperature: float = 0.6,
    max_tokens: int = 8192,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> ChatCompletionResult:
    """
    非流式调用 OpenAI 兼容 /v1/chat/completions 接口。

    用于 Function Calling / Tool Use 场景——第一轮调用带 ``tools``
    让 LLM 判断是否需要调用工具。该轮不需要流式输出。

    Parameters
    ----------
    messages    : 对话消息列表
    model       : 模型名称，默认取 settings.chat_model_name
    temperature : 采样温度
    max_tokens  : 最大输出 token 数
    tools       : OpenAI-compatible tools schema 列表
    tool_choice : "auto" / "none" / {"type": "function", "function": {"name": ...}}
    api_key     : API Key
    base_url    : API 端点

    Returns
    -------
    ChatCompletionResult : 包含 content / reasoning / tool_calls / finish_reason
    """
    effective_model = model or settings.chat_model_name
    effective_key = api_key or settings.openai_api_key
    effective_base = (base_url or settings.openai_base_url or "").rstrip("/")
    url = f"{effective_base}/chat/completions"

    payload: Dict[str, Any] = {
        "model": effective_model,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice

    headers = {
        "Authorization": f"Bearer {effective_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    choices = data.get("choices") or []
    if not choices:
        return ChatCompletionResult()

    choice = choices[0]
    message = choice.get("message") or {}
    finish_reason = choice.get("finish_reason") or ""

    content = message.get("content") or ""
    reasoning = message.get("reasoning_content") or ""

    tool_calls_raw = message.get("tool_calls") or []
    tool_calls: List[ToolCallResult] = []
    for tc in tool_calls_raw:
        func = tc.get("function") or {}
        tool_calls.append(
            ToolCallResult(
                id=tc.get("id") or "",
                name=func.get("name") or "",
                arguments=func.get("arguments") or "{}",
            )
        )

    return ChatCompletionResult(
        content=content,
        reasoning=reasoning,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
    )
