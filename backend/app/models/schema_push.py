from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, TypeAdapter, field_validator, model_validator

# 与简报管线（EmailMessageRenderer.SOURCE_LABELS / get_top_items）保持同一词汇表。
SubscriptionSource = Literal[
    "all", "arxiv", "github", "news", "producthunt", "hackernews", "x", "dailyhot"
]
# 简报仅按日生成，订阅频率只保留 daily（weekly/monthly 已随简报周期一并移除）。
SubscriptionFrequency = Literal["daily"]

_EMAIL_ADAPTER = TypeAdapter(EmailStr)
_MAX_TARGET_LENGTH = 2048


class CreatePushChannelRequest(BaseModel):
    channel_type: Literal["email", "webhook"] = "email"
    target: str

    @model_validator(mode="after")
    def _validate_target_by_type(self) -> "CreatePushChannelRequest":
        target = self.target.strip()
        if not target or len(target) > _MAX_TARGET_LENGTH:
            raise ValueError("target is required and must be at most 2048 chars")
        if self.channel_type == "email":
            # 保持 EmailStr 级别的 422 语义；webhook 的深度校验（https/SSRF）
            # 在服务层完成，返回领域错误而非 422。
            self.target = _EMAIL_ADAPTER.validate_python(target)
        else:
            self.target = target
        return self


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
