"""Wire models for the browser-mediated OAuth handoff flow."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

OAuthProvider = Literal["github", "google", "wechat", "qq", "linuxdo"]
# OAuth 操作判别：login（游客登录，可建号/合并）与 bind（已登录绑定渠道）
# 共用同一 provider 回调路径，但 state/handoff 以操作标记互相隔离，
# 登录态产物永远不能用于绑定，反之亦然。
OAuthOperation = Literal["login", "bind"]
OAuthBindStatus = Literal["bound", "already_bound"]


class OAuthCallbackQuery(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=8192)
    state: str = Field(min_length=1, max_length=512)
    error: str | None = Field(default=None, max_length=128)
    error_description: str | None = Field(default=None, max_length=1024)


class OAuthConsumeResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    role: str
    redirect_to: str = "/"


class OAuthBindConsumeResponse(BaseModel):
    """绑定完成的回执：不签发任何会话令牌，仅回显渠道与结果供前端刷新投影。"""

    provider: OAuthProvider
    status: OAuthBindStatus
    redirect_to: str = "/"


class OAuthErrorResponse(BaseModel):
    code: str
    message: str


class OAuthStartQuery(BaseModel):
    redirect_to: str = Field(default="/", max_length=2048)


class OAuthStartResponse(BaseModel):
    authorization_url: str
    expires_in: int


class OAuthBindStartResponse(BaseModel):
    authorization_url: str


class OAuthStatePayload(BaseModel):
    provider: OAuthProvider
    redirect_to: str = Field(min_length=1, max_length=2048)
    pkce_verifier: str | None = Field(default=None, min_length=43, max_length=128)
    nonce: str | None = Field(default=None, min_length=16, max_length=256)
    browser_binding_hash: str = Field(min_length=64, max_length=64)
    # 存量 Redis 中的登录态 state 无 operation 字段，缺省按 login 兼容解析
    operation: OAuthOperation = "login"
    # 绑定目标账户只存在于服务端 state 中，绝不出现在重定向 URL 里
    target_user_id: int | None = Field(default=None, gt=0)
    # 发起时命中的备用入口 origin；None 即 canonical（存量 state 无此字段同样按 None）。
    # 回调据此复用同一 redirect_uri，并回跳到同一入口（host-only cookie 只在该入口可见）。
    entry_base_url: str | None = Field(default=None, min_length=8, max_length=1024)

    @model_validator(mode="after")
    def _validate_operation_fields(self) -> "OAuthStatePayload":
        if self.operation == "bind":
            if self.target_user_id is None:
                raise ValueError("bind state requires a positive target_user_id")
        elif self.target_user_id is not None:
            raise ValueError("login state must not carry target_user_id")
        return self


class OAuthHandoffPayload(BaseModel):
    user_id: int = Field(gt=0)
    redirect_to: str = Field(min_length=1, max_length=2048)
    browser_binding_hash: str = Field(min_length=64, max_length=64)


class OAuthBindHandoffPayload(BaseModel):
    """绑定专用一次性 handoff：独立于登录 handoff 的模型与 Redis 命名空间。"""

    user_id: int = Field(gt=0)
    provider: OAuthProvider
    status: OAuthBindStatus
    redirect_to: str = Field(min_length=1, max_length=2048)
    browser_binding_hash: str = Field(min_length=64, max_length=64)
