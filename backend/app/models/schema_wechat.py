from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

WeChatLoginStatus = Literal[
    "waiting_scan",
    "scanned_waiting_confirmation",
    "confirmed",
    "completed",
    "qr_expired",
    "failed",
    "cancelled",
]


class WeChatErrorResponse(BaseModel):
    code: str
    message: str


class WeChatLoginAttemptResponse(BaseModel):
    attempt_id: UUID
    status: WeChatLoginStatus
    expires_at: datetime | None = None
    error_code: str | None = None


class WeChatSessionResponse(BaseModel):
    connected: bool
    status: Literal["disconnected", "active", "invalid"]
    account_name: str = ""
    account_avatar_url: str = ""
    last_validated_at: datetime | None = None
    last_used_at: datetime | None = None
    expires_at: datetime | None = None
    invalid_reason_code: str | None = None


class WeChatAccountSaveRequest(BaseModel):
    fakeid: str = Field(min_length=1, max_length=255)
    nickname: str = Field(default="", max_length=255)
    alias: str = Field(default="", max_length=255)
    avatar_url: str = Field(default="", max_length=2048)
    signature: str = Field(default="", max_length=2000)
    enabled: bool = True
    sort_order: int = 0


class WeChatOfficialAccountResponse(BaseModel):
    id: int | None = None
    fakeid: str
    nickname: str = ""
    alias: str = ""
    avatar_url: str = ""
    signature: str = ""
    enabled: bool = True
    sort_order: int = 0
    last_sync_status: str = "never"
    last_sync_message: str = ""
    last_sync_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WeChatOfficialAccountListResponse(BaseModel):
    items: list[WeChatOfficialAccountResponse]
    total: int
    begin: int = 0
    size: int = 0


class WeChatArticleResponse(BaseModel):
    id: int | None = None
    account_id: int
    stable_article_key: str
    message_id: str = ""
    itemidx: int = Field(default=1, ge=1)
    title: str = ""
    digest: str = ""
    author: str = ""
    article_url: str = ""
    cover_url: str = ""
    source_url: str = ""
    published_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WeChatArticleListResponse(BaseModel):
    items: list[WeChatArticleResponse]
    total: int
    offset: int = 0
    limit: int = 20


class WeChatSyncSubmitResponse(BaseModel):
    status: Literal["submitted"] = "submitted"
    account_id: int
    message: str


class WeChatCatalogAccountResponse(BaseModel):
    """User-facing catalog account: display fields only, no owner/sync internals."""

    id: int
    nickname: str = ""
    alias: str = ""
    avatar_url: str = ""
    signature: str = ""
    sort_order: int = 0
    followed: bool = False


class WeChatCatalogListResponse(BaseModel):
    items: list[WeChatCatalogAccountResponse]
    total: int


class WeChatFollowStateResponse(BaseModel):
    account_id: int
    followed: bool


class WeChatFeedAccountEntry(BaseModel):
    account: WeChatCatalogAccountResponse
    articles: list[WeChatArticleResponse] = Field(default_factory=list)


class WeChatFeedResponse(BaseModel):
    items: list[WeChatFeedAccountEntry]
    per_account: int = 5
