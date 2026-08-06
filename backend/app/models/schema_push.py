from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, field_validator

# 与简报管线（EmailMessageRenderer.SOURCE_LABELS / get_top_items）保持同一词汇表。
SubscriptionSource = Literal[
    "all", "arxiv", "github", "news", "producthunt", "hackernews", "x"
]
SubscriptionFrequency = Literal["daily", "weekly", "monthly"]


class CreatePushChannelRequest(BaseModel):
    channel_type: Literal["email"] = "email"
    target: EmailStr


class VerifyPushChannelRequest(BaseModel):
    code: str

    @field_validator("code")
    @classmethod
    def _validate_code(cls, value: str) -> str:
        if not re.fullmatch(r"\d{6}", value):
            raise ValueError("code must be exactly 6 digits")
        return value


class UpdatePushChannelRequest(BaseModel):
    status: Literal["active", "disabled"]


class PushChannelResponse(BaseModel):
    id: int
    channel_type: str
    target: str
    verified: bool
    status: str
    created_at: datetime


class CreateSubscriptionRequest(BaseModel):
    channel_id: int
    source: SubscriptionSource = "all"
    frequency: SubscriptionFrequency = "daily"


class UpdateSubscriptionRequest(BaseModel):
    status: Literal["active", "paused"]


class SubscriptionResponse(BaseModel):
    id: int
    channel_id: int
    channel_type: str
    target: str
    source: str
    frequency: str
    status: str
    created_at: datetime
