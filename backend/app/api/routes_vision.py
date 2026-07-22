"""
Vision Relay API：截图先上传缓存，再用 image_id 做流式视觉问答，Zero-Disk。

POST /api/chat/upload-screenshot
  请求体（JSON）：
    image_base64 str  — 截图的 Base64 字符串（不含 data: 前缀）
    mime_type    str  — 图片 MIME，默认 "image/jpeg"
  响应：{ "image_id": "<uuid>" }  — TTL 5 分钟

POST /api/chat/vision-relay
  请求体（JSON）：
    paper_id  str | None  — 当前阅读的论文 ID（可选）
    question  str         — 用户的追问
    image_id  str         — 由 upload-screenshot 返回的 image_id
    history   list[dict]  — 可选，对话历史 [{role,content}]

处理流程：
  1. 从内存缓存取图 base64，直接 inline 传给 SiliconFlow
  2. 调用 Pro/moonshotai/Kimi-K2.5 流式输出

严格约束：
  - 图片 Base64 只存在于内存缓存，绝不写盘（无任何 open(wb)）
  - 模型通过 https://api.siliconflow.cn/v1
"""

from __future__ import annotations

import asyncio
import json
import time
import traceback
import uuid
from typing import AsyncGenerator, Dict, List, Optional, Tuple

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from backend.app.core.auth import RequireUser
from backend.app.core.config import settings

router = APIRouter()

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

_VISION_BASE_URL = "https://api.siliconflow.cn/v1"
_VISION_MODEL = "Pro/moonshotai/Kimi-K2.5"

_SCREENSHOT_TTL = 300  # 5 分钟

_VISION_SYSTEM = (
    "你是一位顶级 AI 研究员，擅长深度解读学术论文中的图表、公式、文字与实验结果。"
    "你将直接看到用户截取的论文区域图片，并结合用户的追问给出有见地的深度分析回答。"
    "回答要简洁有力，直接切中要点。"
)

# ---------------------------------------------------------------------------
# 内存截图缓存  { image_id: (base64_str, mime_type, expire_ts) }
# ---------------------------------------------------------------------------

_screenshot_cache: Dict[str, Tuple[str, str, float]] = {}
_cache_lock = asyncio.Lock()


async def _evict_expired() -> None:
    """清理过期条目（每次写入时顺手清理）。"""
    now = time.time()
    expired = [k for k, (_, _, ts) in _screenshot_cache.items() if ts < now]
    for k in expired:
        del _screenshot_cache[k]


# ---------------------------------------------------------------------------
# 请求/响应体
# ---------------------------------------------------------------------------


class UploadScreenshotRequest(BaseModel):
    image_base64: str = Field(..., min_length=10)
    mime_type: str = Field(default="image/jpeg")


class UploadScreenshotResponse(BaseModel):
    image_id: str


class VisionRelayRequest(BaseModel):
    paper_id: Optional[str] = None
    question: str = Field(..., min_length=1, max_length=2000)
    image_id: str = Field(
        ..., min_length=1, description="由 upload-screenshot 返回的 image_id"
    )
    history: List[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _sse(event_type: str, data: str) -> str:
    payload = json.dumps({"type": event_type, "data": data}, ensure_ascii=False)
    return f"data: {payload}\n\n"


# ---------------------------------------------------------------------------
# 上传截图接口
# ---------------------------------------------------------------------------


@router.post("/chat/upload-screenshot", response_model=UploadScreenshotResponse)
async def upload_screenshot(
    request: UploadScreenshotRequest,
    _: dict = Depends(RequireUser),
) -> UploadScreenshotResponse:
    """
    接收截图 base64，存入内存缓存（TTL 5 分钟），返回 image_id。
    """
    image_id = str(uuid.uuid4())
    # 清理可能存在的 data URI 前缀（前端有时会带上 data:image/...;base64, ）
    b64 = request.image_base64
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[-1]
    expire_ts = time.time() + _SCREENSHOT_TTL

    async with _cache_lock:
        await _evict_expired()
        _screenshot_cache[image_id] = (b64, request.mime_type, expire_ts)

    return UploadScreenshotResponse(image_id=image_id)


# ---------------------------------------------------------------------------
# 核心流生成器 — 使用 httpx 直接调 SiliconFlow 原始 API（绕过 openai SDK 对 data URI 的限制）
# ---------------------------------------------------------------------------


async def _vision_relay_stream(req: VisionRelayRequest) -> AsyncGenerator[str, None]:
    """
    单棒流式视觉问答：从缓存取 base64 → 用 httpx 直调 SiliconFlow → 流式输出。
    """

    # ── 从缓存取 base64 ───────────────────────────────────────────────────
    async with _cache_lock:
        entry = _screenshot_cache.get(req.image_id)

    if entry is None or time.time() > entry[2]:
        if entry is not None:
            async with _cache_lock:
                _screenshot_cache.pop(req.image_id, None)
        yield _sse("error", "截图已过期或不存在，请重新截图后再提问")
        yield "data: [DONE]\n\n"
        return

    b64_str, mime_type, _ = entry
    data_uri = f"data:{mime_type};base64,{b64_str}"

    try:
        yield _sse("status", "🔍 正在分析图像内容…")

        # 当前轮：图片 + 问题
        user_text = req.question
        if req.paper_id:
            user_text = f"（当前论文 ID：{req.paper_id}）\n{user_text}"

        # 组装消息
        messages: list = [
            {"role": "system", "content": _VISION_SYSTEM},
        ]
        for h in req.history[-12:]:
            if isinstance(h, dict) and h.get("role") and h.get("content"):
                messages.append({"role": h["role"], "content": str(h["content"])})

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
            "model": _VISION_MODEL,
            "messages": messages,
            "max_tokens": 4096,
            "temperature": 0.7,
            "stream": True,
        }

        headers = {
            "Authorization": f"Bearer {settings.siliconflow_api_key}",
            "Content-Type": "application/json",
        }

        # 带退避重试，最多 3 次
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    async with client.stream(
                        "POST",
                        f"{_VISION_BASE_URL}/chat/completions",
                        json=payload,
                        headers=headers,
                    ) as resp:
                        if resp.status_code != 200:
                            body = await resp.aread()
                            err_text = body.decode("utf-8", errors="replace")
                            # 429 限速 → 退避重试
                            if resp.status_code == 429:
                                raise Exception(f"429 rate limit: {err_text}")
                            raise Exception(
                                f"Error code: {resp.status_code} - {err_text}"
                            )

                        async for line in resp.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            data_str = line[5:].strip()
                            if data_str == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data_str)
                                choices = chunk.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    content = delta.get("content")
                                    if content:
                                        yield _sse("content", content)
                            except json.JSONDecodeError:
                                continue
                # 成功完成，跳出重试循环
                break

            except Exception as exc:
                if attempt == 2:
                    raise
                err_str = str(exc)
                is_rate_limit = (
                    "429" in err_str
                    or "rate_limit" in err_str
                    or "rate limit" in err_str.lower()
                )
                wait = 30 * (attempt + 1) if is_rate_limit else 2 ** (attempt + 1)
                yield _sse(
                    "status",
                    f"⏳ {'触发限速，' if is_rate_limit else '模型繁忙，'}{wait}s 后重试（第 {attempt + 1} 次）…",
                )
                await asyncio.sleep(wait)

    except Exception as exc:
        traceback.print_exc()
        yield _sse("error", f"视觉分析失败：{exc}")

    finally:
        yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# 视觉问答路由端点
# ---------------------------------------------------------------------------


@router.post("/chat/vision-relay")
async def vision_relay(
    request_body: VisionRelayRequest,
    _: dict = Depends(RequireUser),
) -> StreamingResponse:
    """
    单棒流式视觉问答（Zero-Disk）：
    - 前端先调用 /chat/upload-screenshot 上传截图，拿到 image_id
    - 本接口从内存缓存取 base64，用 httpx 直调 SiliconFlow API 流式输出
    """
    return StreamingResponse(
        _vision_relay_stream(request_body),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Encoding": "identity",
        },
    )
