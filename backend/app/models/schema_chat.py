from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

ConversationScope = Literal["global", "paper"]
ChatRole = Literal["user", "assistant"]
StreamPhase = Literal["idle", "searching", "reranking", "answering", "error"]


class ChatMessagePayload(BaseModel):
    role: ChatRole
    content: str = ""


class ChatAttachmentRef(BaseModel):
    id: int | str
    name: str = ""
    mime_type: str = ""
    modality: Literal["image", "pdf"] = "image"
    parse_status: str = "uploaded"
    page_count: Optional[int] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class ChatMessageDTO(BaseModel):
    id: int | str
    conversation_id: int | str
    role: ChatRole
    content: str = ""
    thinking: str = ""
    thinking_preview: str = ""
    has_thinking: bool = False
    is_thinking: bool = False
    is_streaming: bool = False
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    attachments: List[ChatAttachmentRef] = Field(default_factory=list)
    parent_message_id: Optional[int | str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ConversationSummaryDTO(BaseModel):
    id: int | str
    title: str = ""
    scope: ConversationScope = "global"
    scope_key: Optional[str] = None
    last_message_preview: str = ""
    message_count: int = 0
    updated_at: Optional[datetime] = None
    last_accessed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class ConversationListResponse(BaseModel):
    items: List[ConversationSummaryDTO] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class ConversationDetailResponse(BaseModel):
    conversation: ConversationSummaryDTO
    messages: List[ChatMessageDTO] = Field(default_factory=list)


class EnsureConversationRequest(BaseModel):
    scope: ConversationScope = "global"
    scope_key: Optional[str] = None
    title: Optional[str] = None


class CreateConversationRequest(BaseModel):
    scope: ConversationScope = "global"
    scope_key: Optional[str] = None
    title: Optional[str] = None


class DeleteConversationResponse(BaseModel):
    detail: str = "删除成功"
    conversation_id: int | str


class DeleteMessageResponse(BaseModel):
    detail: str = "删除成功"
    deleted_ids: List[int] = Field(default_factory=list)
    conversation_id: int | str


class ChatStreamRequest(BaseModel):
    message: str
    history: List[ChatMessagePayload] = Field(default_factory=list)
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    attachment_ids: List[str] = Field(default_factory=list)
    conversation_id: Optional[int] = None
    paper_id: Optional[str] = None
    scope: ConversationScope = "global"
    # 联网搜索开关：True 时在 RAG 检索结果之外附加实时互联网搜索结果
    web_search: bool = False


class RegenerateRequest(BaseModel):
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
