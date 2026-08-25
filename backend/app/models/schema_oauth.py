"""Wire models for the browser-mediated OAuth handoff flow."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

OAuthProvider = Literal["github", "google", "wechat"]


class OAuthCallbackQuery(BaseModel):
    code: str = Field(min_length=1, max_length=8192)
    state: str = Field(min_length=1, max_length=512)
    error: str | None = Field(default=None, max_length=128)
    error_description: str | None = Field(default=None, max_length=1024)


class OAuthConsumeResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    role: str
    redirect_to: str = "/"


class OAuthErrorResponse(BaseModel):
    code: str
    message: str


class OAuthStartQuery(BaseModel):
    redirect_to: str = Field(default="/", max_length=2048)


class OAuthStatePayload(BaseModel):
    provider: OAuthProvider
    redirect_to: str = Field(min_length=1, max_length=2048)
    pkce_verifier: str | None = Field(default=None, min_length=43, max_length=128)
    nonce: str | None = Field(default=None, min_length=16, max_length=256)
    browser_binding_hash: str = Field(min_length=64, max_length=64)


class OAuthHandoffPayload(BaseModel):
    user_id: int = Field(gt=0)
    redirect_to: str = Field(min_length=1, max_length=2048)
    browser_binding_hash: str = Field(min_length=64, max_length=64)
