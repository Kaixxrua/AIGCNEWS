from __future__ import annotations

"""持久化聊天流编排：附件解析、消息增强、RAG 转发与流后持久化。

传输层（SSE 帧序列化、错误帧、[DONE] 终止帧）保留在 api/routes_chat.py；
本模块只产出结构化事件 payload。
"""

import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional

from backend.app.models.schema_chat import ChatStreamRequest
from backend.app.services.chat import attachment_service
from backend.app.services.chat.attachment_service import AttachmentStatus, AttachmentType
from backend.app.services.chat.conversation_service import ConversationService
from backend.app.services.rag.chat_service import ChatService

# PDF 附件注入上下文的最大字符数：防止整篇文档撑爆模型上下文窗口。
PDF_CONTEXT_MAX_CHARS = 8000
# 自动命名会话标题时取用户消息前缀的最大长度。
CONVERSATION_TITLE_MAX_CHARS = 60
# 请求未显式提供 temperature 时的默认采样温度。
DEFAULT_CHAT_TEMPERATURE = 0.7
# 会话作用域合法值；paper_id 只表示"当前阅读论文"的 RAG 上下文，
# 不能强制改变会话作用域，scope 必须跟随请求中的会话自身。
_VALID_SCOPES = ("global", "paper")


def _build_attachment_refs(attachment_ids: List[str]) -> List[Dict[str, Any]]:
    return [{"id": attachment_id} for attachment_id in attachment_ids if attachment_id]


async def _resolve_attachment_context(
    attachment_ids: List[str],
    user_id: int,
) -> tuple[str, List[str]]:
    """解析当前用户拥有的 READY 附件，返回（注入上下文, 归属附件 id 列表）。"""
    attachment_context = ""
    owned_attachment_ids: List[str] = []
    for aid in attachment_ids:
        meta = await attachment_service.get_attachment(aid, user_id)
        if meta is None or meta.status != AttachmentStatus.READY:
            continue
        owned_attachment_ids.append(aid)
        if meta.type == AttachmentType.PDF:
            pdf_text = await attachment_service.get_pdf_text(aid, user_id)
            if pdf_text:
                truncated = pdf_text[:PDF_CONTEXT_MAX_CHARS]
                attachment_context += (
                    f"\n\n[用户上传的 PDF 文件: {meta.filename}]\n"
                    f"{truncated}\n"
                    f"[PDF 内容结束，共 {meta.page_count} 页]\n"
                )
        elif meta.type == AttachmentType.IMAGE:
            attachment_context += f"\n\n[用户上传了图片: {meta.filename}，如需视觉分析请使用视觉问答功能]\n"
    return attachment_context, owned_attachment_ids


async def stream_persisted_chat_events(
    request: ChatStreamRequest,
    user_payload: dict,
    *,
    history_override: Optional[List[dict]] = None,
    message_override: Optional[str] = None,
    conversation_id_override: Optional[int] = None,
    conversation_service: ConversationService,
    rag_service: ChatService,
) -> AsyncIterator[Dict[str, Any]]:
    """真流式：边收边 yield 事件 payload，持久化后置异步。"""
    user_id = int(user_payload.get("user_id") or 0)
    if user_id <= 0:
        raise ValueError("invalid_user")

    attachment_context, owned_attachment_ids = await _resolve_attachment_context(
        request.attachment_ids or [],
        user_id,
    )

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
        temperature=request.temperature or DEFAULT_CHAT_TEMPERATURE,
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

        yield payload

    # ── 后置持久化（流结束后） ──────────────────────────────
    thinking_text = "".join(thinking_parts)
    answer_text = "".join(content_parts)
    requested_scope = request.scope or "global"
    scope = requested_scope if requested_scope in _VALID_SCOPES else "global"
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
        title=raw_message[:CONVERSATION_TITLE_MAX_CHARS] if raw_message else None,
    )

    yield {
        "type": "conversation",
        "data": {
            "conversation_id": persisted["conversation"]["id"],
            "message_id": persisted["assistant_message"]["id"],
        },
    }
