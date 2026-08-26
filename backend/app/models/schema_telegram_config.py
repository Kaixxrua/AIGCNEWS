from __future__ import annotations

from pydantic import BaseModel, Field


class TelegramConfigRequest(BaseModel):
    enabled: bool = False
    bot_token: str | None = Field(default=None, max_length=4096)
    bot_username: str = Field(default="", max_length=255)
    webhook_secret: str | None = Field(default=None, max_length=4096)
    link_ttl_seconds: int = Field(default=300, ge=60, le=3600)
    request_timeout_seconds: float = Field(default=5.0, ge=1.0, le=30.0)
    clear_bot_token: bool = False
    clear_webhook_secret: bool = False


class TelegramWebhookStatus(BaseModel):
    url: str = ""
    pending_update_count: int | None = None
    last_error_message: str | None = None


class TelegramConfigResponse(BaseModel):
    enabled: bool
    bot_username: str
    link_ttl_seconds: int
    request_timeout_seconds: float
    source: str
    updated_at: str | None = None
    bot_token_configured: bool
    bot_token_masked: str | None = None
    webhook_secret_configured: bool
    webhook_secret_masked: str | None = None
    webhook: TelegramWebhookStatus | None = None
