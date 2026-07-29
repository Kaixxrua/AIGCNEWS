from __future__ import annotations

import asyncio
import json
import traceback
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import StreamingResponse

from backend.app.core.auth import RequireUser
from backend.app.core.config import settings
from backend.app.api.dependencies import (
    get_conversation_repository,
    get_document_repository,
)
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
from backend.app.repositories.document_repository import DocumentRepository
from backend.app.repositories.graph_repo import GraphRepository
from backend.app.repositories.milvus_repo import MilvusRepository
from backend.app.services.chat.conversation_service import ConversationService
from backend.app.services.chat.quota_policy import check_user_message_limit
from backend.app.services.rag.chat_service import ChatService
from backend.app.services.rag.retriever import HybridRetriever

router = APIRouter()


def _check_user_message_limit(user_payload: dict, quota_reader: ConversationRepository) -> None:
    """Compatibility seam for the shared chat quota policy."""
    check_user_message_limit(
        user_payload,
        quota_reader,
        limit=settings.USER_DAILY_MESSAGE_LIMIT,
    )


def _build_attachment_refs(attachment_ids: List[str]) -> List[Dict[str, Any]]:
    return [{"id": attachment_id} for attachment_id in attachment_ids if attachment_id]


async def _stream_persisted_chat(
    request: ChatStreamRequest,
    user_payload: dict,
    *,
    history_override: Optional[List[dict]] = None,
    message_override: Optional[str] = None,
    conversation_id_override: Optional[int] = None,
    conversation_repository: ConversationRepository,
    documents: DocumentRepository,
) -> AsyncGenerator[str, None]:
    """真流式 SSE：边收边 yield，持久化后置异步。"""
    try:
        user_id = int(user_payload.get("user_id") or 0)
        if user_id <= 0:
            raise ValueError("invalid_user")

        retriever = HybridRetriever(
            MilvusRepository(),
            GraphRepository(),
            documents,
            documents,
        )
        rag_service = ChatService(
            retriever,
            ranking_reader=documents,
            statistics_reader=documents,
        )
        conversation_service = ConversationService(conversation_repository)

        attachment_context = ""
        attachment_ids = request.attachment_ids or []
        owned_attachment_ids: List[str] = []
        if attachment_ids:
            from backend.app.services.chat.attachment_service import (
                AttachmentStatus,
                AttachmentType,
                get_attachment,
                get_pdf_text,
            )

            for aid in attachment_ids:
                meta = await get_attachment(aid, user_id)
                if meta is None or meta.status != AttachmentStatus.READY:
                    continue
                owned_attachment_ids.append(aid)
                if meta.type == AttachmentType.PDF:
                    pdf_text = await get_pdf_text(aid, user_id)
                    if pdf_text:
                        truncated = pdf_text[:8000]
                        attachment_context += (
                            f"\n\n[用户上传的 PDF 文件: {meta.filename}]\n"
                            f"{truncated}\n"
                            f"[PDF 内容结束，共 {meta.page_count} 页]\n"
                        )
                elif meta.type == AttachmentType.IMAGE:
                    attachment_context += f"\n\n[用户上传了图片: {meta.filename}，如需视觉分析请使用视觉问答功能]\n"

        raw_message = (
            message_override if message_override is not None else request.message
        ).strip()
        enhanced_message = raw_message
        if attachment_context:
            enhanced_message = (
                f"{enhanced_message}\n\n--- 附件内容 ---{attachment_context}"
            )
        if request.paper_id:
            enhanced_message = (
                f"（当前用户正在阅读论文 ID: {request.paper_id}）\n{enhanced_message}"
            )

        history = (
            history_override
            if history_override is not None
            else [
                item.model_dump() if hasattr(item, "model_dump") else dict(item)
                for item in request.history
            ]
        )

        # ── 真流式：边收边 yield，同时收集用于持久化 ──────────────
        sources: List[Dict[str, Any]] = []
        thinking_parts: List[str] = []
        content_parts: List[str] = []

        async for payload in rag_service.stream_chat(
            enhanced_message,
            history=history,
            temperature=request.temperature or 0.7,
            web_search_enabled=request.web_search,
        ):
            # 收集用于后续持久化
            payload_type = payload.get("type")
            if payload_type == "sources" and isinstance(payload.get("data"), list):
                sources = payload["data"]
            elif payload_type == "thinking":
                thinking_parts.append(str(payload.get("data") or ""))
            elif payload_type == "content":
                content_parts.append(str(payload.get("data") or ""))

            # 立即 yield 给前端
            try:
                data = json.dumps(payload, ensure_ascii=False, default=str)
            except Exception:
                data = json.dumps({"type": "error", "data": "serialize_error"})
            yield f"data: {data}\n\n"

        # ── 后置持久化（流结束后） ──────────────────────────────
        thinking_text = "".join(thinking_parts)
        answer_text = "".join(content_parts)
        # paper_id 只表示“当前阅读论文”的 RAG 上下文，不能强制改变会话作用域；
        # PaperReadView 现在与 ChatView 共用 global 会话，scope 必须跟随请求中的会话自身。
        requested_scope = request.scope or "global"
        scope = requested_scope if requested_scope in ("global", "paper") else "global"
        scope_key = request.paper_id if scope == "paper" else None
        persisted = await asyncio.to_thread(
            conversation_service.append_message_pair,
            user_id=user_id,
            conversation_id=conversation_id_override or request.conversation_id,
            scope=scope,
            scope_key=scope_key,
            user_message=raw_message,
            assistant_content=answer_text,
            assistant_thinking=thinking_text,
            sources=sources,
            attachments=_build_attachment_refs(owned_attachment_ids),
            title=raw_message[:60] if raw_message else None,
        )

        conversation_payload = {
            "type": "conversation",
            "data": {
                "conversation_id": persisted["conversation"]["id"],
                "message_id": persisted["assistant_message"]["id"],
            },
        }
        yield f"data: {json.dumps(conversation_payload, ensure_ascii=False, default=str)}\n\n"

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
    documents: DocumentRepository = Depends(get_document_repository),
) -> StreamingResponse:
    _check_user_message_limit(user, conversations)
    return StreamingResponse(
        _stream_persisted_chat(
            request,
            user,
            conversation_repository=conversations,
            documents=documents,
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
    conversations: ConversationRepository = Depends(get_conversation_repository),
) -> ConversationSummaryDTO:
    service = ConversationService(conversations)
    conversation = await asyncio.to_thread(
        service.ensure_conversation,
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
    conversations: ConversationRepository = Depends(get_conversation_repository),
) -> ConversationSummaryDTO:
    """强制创建新会话（不复用已有会话）。"""
    service = ConversationService(conversations)
    conversation = await asyncio.to_thread(
        service.create_new_conversation,
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
    conversations: ConversationRepository = Depends(get_conversation_repository),
) -> DeleteConversationResponse:
    """删除指定会话及其所有消息。"""
    service = ConversationService(conversations)
    success = await asyncio.to_thread(
        service.delete_conversation,
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
    conversations: ConversationRepository = Depends(get_conversation_repository),
) -> ConversationListResponse:
    service = ConversationService(conversations)
    result = await asyncio.to_thread(
        service.list_conversations,
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
    conversations: ConversationRepository = Depends(get_conversation_repository),
) -> ConversationDetailResponse:
    service = ConversationService(conversations)
    try:
        context = await asyncio.to_thread(
            service.get_conversation_context,
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
    conversations: ConversationRepository = Depends(get_conversation_repository),
) -> DeleteMessageResponse:
    service = ConversationService(conversations)
    try:
        result = await asyncio.to_thread(
            service.delete_message,
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
    documents: DocumentRepository = Depends(get_document_repository),
) -> StreamingResponse:
    _check_user_message_limit(user, conversations)
    service = ConversationService(conversations)
    try:
        regen_result = await asyncio.to_thread(
            service.regenerate_from_message,
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
        temperature=request.temperature or 0.7,
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
            conversation_repository=conversations,
            documents=documents,
        ),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Encoding": "identity",
        },
    )
