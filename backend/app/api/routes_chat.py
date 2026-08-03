from __future__ import annotations

import asyncio
import json
import traceback
from typing import AsyncGenerator, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import StreamingResponse

from backend.app.api.dependencies import (
    get_conversation_repository,
    get_conversation_service,
    get_rag_chat_service,
)
from backend.app.core.auth import RequireUser
from backend.app.core.config import settings
from backend.app.models.schema_chat import (
    ChatStreamRequest,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationSummaryDTO,
    CreateConversationRequest,
    DeleteConversationResponse,
    DeleteMessageResponse,
    EnsureConversationRequest,
    RegenerateRequest,
)
from backend.app.repositories.conversation_repository import ConversationRepository
from backend.app.services.chat.conversation_service import ConversationService
from backend.app.services.chat.persisted_chat_stream import (
    DEFAULT_CHAT_TEMPERATURE,
    stream_persisted_chat_events,
)
from backend.app.services.chat.quota_policy import (
    MessageLimitExceededError,
    check_user_message_limit,
)
from backend.app.services.rag.chat_service import ChatService

router = APIRouter()


def _check_user_message_limit(user_payload: dict, quota_reader: ConversationRepository) -> None:
    """Compatibility seam for the shared chat quota policy."""
    try:
        check_user_message_limit(
            user_payload,
            quota_reader,
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


async def _stream_persisted_chat(
    request: ChatStreamRequest,
    user_payload: dict,
    *,
    history_override: Optional[List[dict]] = None,
    message_override: Optional[str] = None,
    conversation_id_override: Optional[int] = None,
    conversation_service: ConversationService,
    rag_service: ChatService,
) -> AsyncGenerator[str, None]:
    """SSE 传输编排：帧序列化 / 错误帧 / [DONE] 终止帧。

    业务编排（附件解析、消息增强、流后持久化）已下沉
    services/chat/persisted_chat_stream.py，此处仅保留线格式。
    """
    try:
        async for payload in stream_persisted_chat_events(
            request,
            user_payload,
            history_override=history_override,
            message_override=message_override,
            conversation_id_override=conversation_id_override,
            conversation_service=conversation_service,
            rag_service=rag_service,
        ):
            # 立即 yield 给前端
            try:
                data = json.dumps(payload, ensure_ascii=False, default=str)
            except Exception:
                data = json.dumps({"type": "error", "data": "serialize_error"})
            yield f"data: {data}\n\n"
    except Exception as exc:
        traceback.print_exc()
        error_payload = json.dumps({"type": "error", "data": str(exc)})
        yield f"data: {error_payload}\n\n"
    finally:
        yield "data: [DONE]\n\n"


@router.post("/chat/stream")
async def stream_chat(
    request: ChatStreamRequest,
    user: dict = Depends(RequireUser),
    conversations: ConversationRepository = Depends(get_conversation_repository),
    conversation_service: ConversationService = Depends(get_conversation_service),
    rag_service: ChatService = Depends(get_rag_chat_service),
) -> StreamingResponse:
    _check_user_message_limit(user, conversations)
    return StreamingResponse(
        _stream_persisted_chat(
            request,
            user,
            conversation_service=conversation_service,
            rag_service=rag_service,
        ),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Encoding": "identity",
        },
    )


@router.post("/chat/conversations/ensure", response_model=ConversationSummaryDTO)
async def ensure_conversation(
    request: EnsureConversationRequest,
    user: dict = Depends(RequireUser),
    conversation_service: ConversationService = Depends(get_conversation_service),
) -> ConversationSummaryDTO:
    conversation = await asyncio.to_thread(
        conversation_service.ensure_conversation,
        user_id=int(user["user_id"]),
        scope=request.scope,
        scope_key=request.scope_key,
        title=request.title,
    )
    return ConversationSummaryDTO.model_validate(conversation)


@router.post("/chat/conversations/create", response_model=ConversationSummaryDTO)
async def create_conversation(
    request: CreateConversationRequest,
    user: dict = Depends(RequireUser),
    conversation_service: ConversationService = Depends(get_conversation_service),
) -> ConversationSummaryDTO:
    """强制创建新会话（不复用已有会话）。"""
    conversation = await asyncio.to_thread(
        conversation_service.create_new_conversation,
        user_id=int(user["user_id"]),
        scope=request.scope,
        scope_key=request.scope_key,
        title=request.title,
    )
    return ConversationSummaryDTO.model_validate(conversation)


@router.delete(
    "/chat/conversations/{conversation_id}",
    response_model=DeleteConversationResponse,
)
async def delete_conversation(
    conversation_id: int,
    user: dict = Depends(RequireUser),
    conversation_service: ConversationService = Depends(get_conversation_service),
) -> DeleteConversationResponse:
    """删除指定会话及其所有消息。"""
    success = await asyncio.to_thread(
        conversation_service.delete_conversation,
        user_id=int(user["user_id"]),
        conversation_id=conversation_id,
    )
    if not success:
        raise HTTPException(status_code=404, detail="会话不存在或无权限")
    return DeleteConversationResponse(
        detail="删除成功",
        conversation_id=conversation_id,
    )


@router.get("/chat/conversations", response_model=ConversationListResponse)
async def get_conversations(
    scope: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(RequireUser),
    conversation_service: ConversationService = Depends(get_conversation_service),
) -> ConversationListResponse:
    result = await asyncio.to_thread(
        conversation_service.list_conversations,
        user_id=int(user["user_id"]),
        scope=scope,
        page=page,
        page_size=page_size,
    )
    return ConversationListResponse.model_validate(result)


@router.get(
    "/chat/conversations/{conversation_id}", response_model=ConversationDetailResponse
)
async def get_conversation_detail(
    conversation_id: int,
    user: dict = Depends(RequireUser),
    conversation_service: ConversationService = Depends(get_conversation_service),
) -> ConversationDetailResponse:
    try:
        context = await asyncio.to_thread(
            conversation_service.get_conversation_context,
            user_id=int(user["user_id"]),
            conversation_id=conversation_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ConversationDetailResponse.model_validate(
        {
            "conversation": context.conversation,
            "messages": context.messages,
        }
    )


@router.delete("/chat/messages/{message_id}", response_model=DeleteMessageResponse)
async def delete_message(
    message_id: int,
    user: dict = Depends(RequireUser),
    conversation_service: ConversationService = Depends(get_conversation_service),
) -> DeleteMessageResponse:
    try:
        result = await asyncio.to_thread(
            conversation_service.delete_message,
            user_id=int(user["user_id"]),
            message_id=message_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DeleteMessageResponse(
        detail="删除成功",
        deleted_ids=result["deleted_ids"],
        conversation_id=result["conversation"]["id"],
    )


@router.post("/chat/messages/{message_id}/regenerate")
async def regenerate_message(
    message_id: int,
    request: RegenerateRequest,
    user: dict = Depends(RequireUser),
    conversations: ConversationRepository = Depends(get_conversation_repository),
    conversation_service: ConversationService = Depends(get_conversation_service),
    rag_service: ChatService = Depends(get_rag_chat_service),
) -> StreamingResponse:
    _check_user_message_limit(user, conversations)
    try:
        regen_result = await asyncio.to_thread(
            conversation_service.regenerate_from_message,
            user_id=int(user["user_id"]),
            message_id=message_id,
        )
    except ValueError as exc:
        if str(exc) == "visual_message_regeneration_not_supported":
            raise HTTPException(
                status_code=409,
                detail="视觉消息需要重新上传截图后才能重新生成",
            ) from exc
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    messages = regen_result["messages"]
    target = regen_result["target_message"]
    history = [
        {"role": item.get("role", "user"), "content": item.get("content", "")}
        for item in messages
        if int(item.get("id", 0)) < int(target["id"])
    ]
    user_message = target["content"]
    stream_request = ChatStreamRequest(
        message=user_message,
        history=history,
        temperature=request.temperature or DEFAULT_CHAT_TEMPERATURE,
        attachment_ids=[],
        conversation_id=int(target["conversation_id"]),
        paper_id=(
            regen_result["conversation"].get("scope_key")
            if regen_result["conversation"].get("scope") == "paper"
            else None
        ),
        scope=regen_result["conversation"].get("scope") or "global",
    )
    return StreamingResponse(
        _stream_persisted_chat(
            stream_request,
            user,
            history_override=history,
            message_override=user_message,
            conversation_id_override=int(target["conversation_id"]),
            conversation_service=conversation_service,
            rag_service=rag_service,
        ),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Encoding": "identity",
        },
    )
