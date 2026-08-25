from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class OAuthConfigRequest(BaseModel):
    enabled_providers: list[Literal["github", "google", "wechat"]] = Field(
        default_factory=list,
    )
    public_base_url: str = Field(default="", max_length=1024)
    github_client_id: str = Field(default="", max_length=512)
    github_client_secret: str | None = Field(default=None, max_length=4096)
    google_client_id: str = Field(default="", max_length=512)
    google_client_secret: str | None = Field(default=None, max_length=4096)
    wechat_app_id: str = Field(default="", max_length=512)
    wechat_app_secret: str | None = Field(default=None, max_length=4096)
    state_ttl_seconds: int = Field(default=300, ge=60, le=900)
    handoff_ttl_seconds: int = Field(default=120, ge=30, le=600)
    clear_github_client_secret: bool = False
    clear_google_client_secret: bool = False
    clear_wechat_app_secret: bool = False


class OAuthConfigResponse(BaseModel):
    enabled_providers: list[str]
    public_base_url: str
    github_client_id: str
    google_client_id: str
    wechat_app_id: str
    state_ttl_seconds: int
    handoff_ttl_seconds: int
    source: str
    updated_at: str | None = None
    github_client_secret_configured: bool
    github_client_secret_masked: str | None = None
    google_client_secret_configured: bool
    google_client_secret_masked: str | None = None
    wechat_app_secret_configured: bool
    wechat_app_secret_masked: str | None = None
