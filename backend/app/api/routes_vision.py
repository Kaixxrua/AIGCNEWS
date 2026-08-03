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
import logging
from typing import Any, AsyncGenerator, List, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from backend.app.api.dependencies import get_conversation_repository
from backend.app.core.auth import RequireUser
from backend.app.core.config import settings
from backend.app.repositories.conversation_repository import ConversationRepository
from backend.app.services.chat.conversation_service import ConversationService
from backend.app.services.chat.quota_policy import (
    MessageLimitExceededError,
    check_user_message_limit,
)
from backend.app.services.vision import relay as vision_relay_service
from backend.app.services.vision.image_cache import ScreenshotImageCache
from backend.app.services.vision.provider import VISION_SYSTEM, VisionProvider

router = APIRouter()

logger = logging.getLogger(__name__)

# 兼容既有模块内访问；消息载荷由 provider 边界持有。
_VISION_SYSTEM = VISION_SYSTEM

_image_cache = ScreenshotImageCache()


def _report_relay_error() -> None:
    """relay 流失败时的服务端错误上报：原始异常只进日志，不外泄给客户端。"""
    logger.exception("[Vision] relay stream failed")


# ---------------------------------------------------------------------------
# 请求/响应体
# ---------------------------------------------------------------------------


class UploadScreenshotRequest(BaseModel):
    image_base64: str = Field(..., min_length=10)
    mime_type: str = Field(default="image/jpeg")


class UploadScreenshotResponse(BaseModel):
    image_id: str


class VisionRelayRequest(BaseModel):
    conversation_id: Optional[int] = None
    paper_id: Optional[str] = None
    question: str = Field(..., min_length=1, max_length=2000)
    image_id: str = Field(
        ..., min_length=1, description="由 upload-screenshot 返回的 image_id"
    )
    history: List[dict] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _sse(event_type: str, data: Any) -> str:
    """兼容既有 monkeypatch seam，实际编码由 relay 边界持有。"""
    return vision_relay_service.encode_sse(event_type, data)


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
    image_id = await _image_cache.put(request.image_base64, request.mime_type)
    return UploadScreenshotResponse(image_id=image_id)


# ---------------------------------------------------------------------------
# 核心流生成器 — 使用 httpx 直接调 SiliconFlow 原始 API（绕过 openai SDK 对 data URI 的限制）
# ---------------------------------------------------------------------------


async def _vision_relay_stream(
    req: VisionRelayRequest,
    *,
    user_id: int | None = None,
    conversation_repository: ConversationRepository | None = None,
) -> AsyncGenerator[str, None]:
    """兼容路由私有入口，将旧 globals 晚绑定转发给 relay 协调边界。"""

    provider = VisionProvider(
        api_key=settings.siliconflow_api_key,
        client_factory=httpx.AsyncClient,
        sleep=asyncio.sleep,
    )
    persist_completed = None
    if user_id is not None and conversation_repository is not None:
        conversation_service = ConversationService(conversation_repository)

        async def persist_completed(answer: str) -> dict[str, Any]:
            return await asyncio.to_thread(
                conversation_service.append_message_pair,
                user_id=user_id,
                conversation_id=req.conversation_id,
                scope="paper" if req.paper_id else "global",
                scope_key=req.paper_id,
                user_message=req.question.strip(),
                assistant_content=answer,
                attachments=[
                    {
                        "modality": "vision",
                        "image_retained": False,
                        "regeneration_requires_new_image": True,
                    }
                ],
                title=req.question.strip()[:60] or None,
            )

    async for chunk in vision_relay_service.stream_vision_relay(
        image_id=req.image_id,
        question=req.question,
        paper_id=req.paper_id,
        history=req.history,
        image_loader=_image_cache.get,
        provider_stream=provider.stream,
        encode_event=_sse,
        report_error=_report_relay_error,
        persist_completed=persist_completed,
    ):
        yield chunk


# ---------------------------------------------------------------------------
# 视觉问答路由端点
# ---------------------------------------------------------------------------


@router.post("/chat/vision-relay")
async def vision_relay(
    request_body: VisionRelayRequest,
    user: dict = Depends(RequireUser),
    conversations: ConversationRepository = Depends(get_conversation_repository),
) -> StreamingResponse:
    """
    单棒流式视觉问答（Zero-Disk）：
    - 前端先调用 /chat/upload-screenshot 上传截图，拿到 image_id
    - 本接口从内存缓存取 base64，用 httpx 直调 SiliconFlow API 流式输出
    """
    try:
        check_user_message_limit(
            user,
            conversations,
            limit=settings.USER_DAILY_MESSAGE_LIMIT,
        )
    except MessageLimitExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "message_limit_exceeded",
                "message": str(exc),
                "limit": exc.limit,
                "used": exc.used,
            },
        ) from exc
    return StreamingResponse(
        _vision_relay_stream(
            request_body,
            user_id=int(user.get("user_id") or 0),
            conversation_repository=conversations,
        ),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Encoding": "identity",
        },
    )
