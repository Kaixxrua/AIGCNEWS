"""MCP OAuth 授权服务器的 HTTP 端点（/api/oauth/*）。

- POST /api/oauth/register：动态客户端注册（RFC 7591）；
- POST /api/oauth/authorize/preview、POST /api/oauth/authorize：前端同意页
  （/oauth/authorize，即元数据里的 authorization_endpoint）调用，须已登录；
- POST /api/oauth/token：授权码换令牌（form 编码，RFC 6749 §4.1.3）。

站点自身的第三方登录在 /api/auth/oauth/*，与这里无关。错误体统一用 RFC 6749 §5.2 的
{"error", "error_description"}；授权码在 Redis，Redis 不可用时所有端点都返回 503。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import unquote_plus

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.dependencies import get_mcp_access_token_repository
from backend.app.api.routes_auth import DEFAULT_MCP_TOKEN_SCOPES, MCP_TOKEN_SCOPES
from backend.app.core.auth import RequireUser, hash_mcp_token
from backend.app.core.client_ip import client_ip_from_request
from backend.app.repositories.mcp_access_token_repository import McpAccessTokenRepository
from backend.app.services.auth.mcp_oauth import (
    MAX_CLIENT_NAME_LENGTH,
    MAX_REDIRECT_URIS,
    MAX_STATE_LENGTH,
    MCP_OAUTH_ISSUER,
    TOKEN_ENDPOINT_AUTH_METHODS,
    AuthorizationCodePayload,
    AuthorizationCodeStore,
    InvalidRedirectUriError,
    McpOAuthUnavailableError,
    canonical_resource,
    client_secret_matches,
    describe_redirect_uri,
    hash_client_secret,
    infer_client_type,
    is_valid_code_challenge,
    new_client_id,
    new_client_secret,
    normalize_client_name,
    redirect_uri_registered,
    redirect_with_params,
    validate_redirect_uri,
    verify_pkce_s256,
)
from backend.app.services.auth.rate_limit import RateLimitExceededError, hit_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_RATE_LIMIT_WINDOW_SECONDS = 600
_REGISTER_PER_IP_LIMIT = 20
# 全站注册总量封顶：动态注册不要求登录，防止脚本灌满客户端表
_REGISTER_GLOBAL_LIMIT = 200
_PREVIEW_PER_USER_LIMIT = 60
_AUTHORIZE_PER_USER_LIMIT = 30
_TOKEN_PER_IP_LIMIT = 60
_MAX_REGISTRATION_BYTES = 16 * 1024
_MAX_CLIENT_ID_LENGTH = 64
_TOKEN_FORM_FIELDS = (
    "grant_type",
    "code",
    "redirect_uri",
    "code_verifier",
    "client_id",
    "client_secret",
    "resource",
)
_FALLBACK_CLIENT_LABEL = "MCP OAuth"


class _OAuthFailure(Exception):
    """不能回跳客户端的错误：直接以 JSON 回给调用方。"""

    def __init__(
        self,
        status_code: int,
        error: str,
        description: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(error)
        self.status_code = status_code
        self.error = error
        self.description = description
        self.headers = headers or {}

    def response(self) -> JSONResponse:
        return JSONResponse(
            {"error": self.error, "error_description": self.description},
            status_code=self.status_code,
            headers={**_NO_STORE, **self.headers},
        )


class _AuthorizationErrorRedirect(Exception):
    """客户端与回调地址已核实后的授权请求错误：带回调地址交给同意页（RFC 6749 §4.1.2.1）。"""

    def __init__(self, redirect_uri: str, error: str, description: str, state: str | None) -> None:
        super().__init__(error)
        self.error = error
        self.description = description
        self.redirect_uri = redirect_uri
        self.redirect_to = redirect_with_params(
            redirect_uri,
            {"error": error, "error_description": description, "state": state, "iss": MCP_OAUTH_ISSUER},
        )

    def response(self) -> JSONResponse:
        return JSONResponse(
            {
                "status": "error",
                "error": self.error,
                "error_description": self.description,
                "redirect_to": self.redirect_to,
                "redirect": describe_redirect_uri(self.redirect_uri),
            },
            headers=_NO_STORE,
        )


_UNAVAILABLE = (503, "temporarily_unavailable", "授权服务暂时不可用，请稍后再试")


async def _enforce_limit(request: Request, *, action: str, identity: str, limit: int) -> None:
    """固定窗口限速。授权码本就存在 Redis，Redis 不可用时整个流程都走不通，这里同样拒绝。"""
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        raise _OAuthFailure(*_UNAVAILABLE)
    try:
        await hit_rate_limit(
            redis_client,
            action=action,
            identity=identity,
            limit=limit,
            window_seconds=_RATE_LIMIT_WINDOW_SECONDS,
        )
    except RateLimitExceededError as exc:
        raise _OAuthFailure(429, "temporarily_unavailable", "请求过于频繁，请稍后再试") from exc
    except Exception as exc:
        logger.warning("[MCP OAuth] rate limit check failed, rejecting request", exc_info=True)
        raise _OAuthFailure(*_UNAVAILABLE) from exc


def _code_store(request: Request) -> AuthorizationCodeStore:
    return AuthorizationCodeStore(getattr(request.app.state, "redis", None))


def _user_id(user: dict[str, Any]) -> int:
    try:
        user_id = int(user.get("user_id") or 0)
    except (TypeError, ValueError):
        user_id = 0
    if user_id <= 0:
        raise _OAuthFailure(401, "login_required", "用户身份无效")
    return user_id


def _granted_scopes(requested: str | None) -> list[str]:
    """客户端要的 scope 与本站支持的取交集；一个都不认识时按默认集合授予（RFC 6749 §3.3）。"""
    asked = set((requested or "").split())
    granted = [scope for scope in sorted(MCP_TOKEN_SCOPES) if scope in asked]
    return granted or list(DEFAULT_MCP_TOKEN_SCOPES)


# ---------------------------------------------------------------- registration


@router.post("/oauth/register", status_code=201, summary="MCP OAuth 动态客户端注册（RFC 7591）")
async def register_client(
    request: Request,
    repository: McpAccessTokenRepository = Depends(get_mcp_access_token_repository),
) -> JSONResponse:
    try:
        await _enforce_limit(
            request,
            action="mcp_oauth.register",
            identity=client_ip_from_request(request),
            limit=_REGISTER_PER_IP_LIMIT,
        )
        await _enforce_limit(
            request,
            action="mcp_oauth.register_global",
            identity="all",
            limit=_REGISTER_GLOBAL_LIMIT,
        )
        metadata = await _registration_metadata(request)
        redirect_uris = _registration_redirect_uris(metadata.get("redirect_uris"))
        _require_supported_flow(metadata)
        # RFC 7591 §2：没写认证方式即 client_secret_basic；有的客户端把未设置的字段序列化成 null
        auth_method = metadata.get("token_endpoint_auth_method")
        if auth_method is None:
            auth_method = "client_secret_basic"
        if auth_method not in TOKEN_ENDPOINT_AUTH_METHODS:
            raise _OAuthFailure(
                400,
                "invalid_client_metadata",
                "token_endpoint_auth_method 只支持 none、client_secret_post、client_secret_basic",
            )
    except _OAuthFailure as failure:
        return failure.response()

    client_name = normalize_client_name(metadata.get("client_name"))
    # 公开客户端（none）不发密钥，只靠 PKCE
    client_secret = new_client_secret() if auth_method != "none" else None
    client = await asyncio.to_thread(
        repository.register_mcp_oauth_client,
        client_id=new_client_id(),
        client_name=client_name,
        redirect_uris=redirect_uris,
        token_endpoint_auth_method=auth_method,
        client_secret_hash=hash_client_secret(client_secret) if client_secret else None,
    )
    logger.info(
        "[MCP OAuth] registered client %s (%s) auth=%s redirects=%s",
        client["client_id"],
        client_name or "-",
        auth_method,
        ",".join(describe_redirect_uri(uri)["kind"] for uri in redirect_uris),
    )
    body: dict[str, Any] = {
        "client_id": client["client_id"],
        "client_id_issued_at": int(time.time()),
        "redirect_uris": client["redirect_uris"],
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "token_endpoint_auth_method": auth_method,
    }
    if client_name:
        body["client_name"] = client_name
    if client_secret:
        body["client_secret"] = client_secret
        body["client_secret_expires_at"] = 0
    return JSONResponse(body, status_code=201, headers=_NO_STORE)


async def _registration_metadata(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if len(raw) > _MAX_REGISTRATION_BYTES:
        raise _OAuthFailure(400, "invalid_client_metadata", "注册请求过大")
    try:
        metadata = json.loads(raw)
    except ValueError as exc:
        raise _OAuthFailure(400, "invalid_client_metadata", "注册请求必须是 JSON 对象") from exc
    if not isinstance(metadata, dict):
        raise _OAuthFailure(400, "invalid_client_metadata", "注册请求必须是 JSON 对象")
    name = metadata.get("client_name")
    if name is not None and (not isinstance(name, str) or len(name) > MAX_CLIENT_NAME_LENGTH * 4):
        raise _OAuthFailure(400, "invalid_client_metadata", "client_name 不合法")
    return metadata


def _registration_redirect_uris(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > MAX_REDIRECT_URIS:
        raise _OAuthFailure(
            400,
            "invalid_redirect_uri",
            f"redirect_uris 必须是 1 到 {MAX_REDIRECT_URIS} 个回调地址",
        )
    try:
        validated = [validate_redirect_uri(uri) for uri in value]
    except InvalidRedirectUriError as exc:
        raise _OAuthFailure(400, "invalid_redirect_uri", str(exc)) from exc
    return list(dict.fromkeys(validated))


def _require_supported_flow(metadata: dict[str, Any]) -> None:
    """只支持授权码流程：客户端声明的 grant/response 类型里必须有它。

    额外声明的类型（如 refresh_token）不报错，响应里只回本站实际支持的值（RFC 7591 §3.2.1）。
    """
    grant_types = metadata.get("grant_types")
    if grant_types is not None and (
        not isinstance(grant_types, list) or "authorization_code" not in grant_types
    ):
        raise _OAuthFailure(400, "invalid_client_metadata", "grant_types 必须包含 authorization_code")
    response_types = metadata.get("response_types")
    if response_types is not None and (
        not isinstance(response_types, list) or "code" not in response_types
    ):
        raise _OAuthFailure(400, "invalid_client_metadata", "response_types 必须包含 code")


# ---------------------------------------------------------------- authorization


class AuthorizationRequestBody(BaseModel):
    """同意页原样转发的授权请求参数（authorization_endpoint 的查询串）。"""

    model_config = ConfigDict(extra="ignore")

    response_type: str | None = Field(default=None, max_length=64)
    client_id: str | None = Field(default=None, max_length=256)
    redirect_uri: str | None = Field(default=None, max_length=4096)
    state: str | None = Field(default=None, max_length=8192)
    code_challenge: str | None = Field(default=None, max_length=256)
    code_challenge_method: str | None = Field(default=None, max_length=64)
    scope: str | None = Field(default=None, max_length=2048)
    resource: str | None = Field(default=None, max_length=4096)


class AuthorizationDecisionBody(AuthorizationRequestBody):
    decision: Literal["approve", "deny"]


@dataclass(frozen=True, slots=True)
class _ResolvedAuthorization:
    client: dict[str, Any]
    redirect_uri: str
    state: str | None
    code_challenge: str
    scopes: list[str]
    resource: str


async def _resolve_authorization(
    body: AuthorizationRequestBody,
    repository: McpAccessTokenRepository,
) -> _ResolvedAuthorization:
    """按 RFC 6749 §4.1.2.1 的顺序校验授权请求。

    客户端未知、回调地址缺失或不在登记范围内时绝不回跳（_OAuthFailure）；
    之后的错误带上回调地址交给同意页，由用户点击返回客户端（_AuthorizationErrorRedirect）。
    """
    client_id = body.client_id or ""
    if not client_id:
        raise _OAuthFailure(400, "invalid_request", "缺少 client_id")
    client = None
    if len(client_id) <= _MAX_CLIENT_ID_LENGTH:
        client = await asyncio.to_thread(repository.get_mcp_oauth_client, client_id)
    if client is None:
        raise _OAuthFailure(400, "invalid_client", "客户端未注册或注册已失效，请在 MCP 客户端里重新连接")
    redirect_uri = body.redirect_uri
    if not redirect_uri:
        raise _OAuthFailure(400, "invalid_redirect_uri", "缺少 redirect_uri")
    try:
        validate_redirect_uri(redirect_uri)
    except InvalidRedirectUriError as exc:
        raise _OAuthFailure(400, "invalid_redirect_uri", str(exc)) from exc
    if not redirect_uri_registered(client["redirect_uris"], redirect_uri):
        raise _OAuthFailure(400, "invalid_redirect_uri", "redirect_uri 与客户端注册时登记的不一致")

    state = body.state
    if state is not None and len(state) > MAX_STATE_LENGTH:
        # 超长 state 不回传，免得回跳地址被撑大
        raise _AuthorizationErrorRedirect(redirect_uri, "invalid_request", "state 过长", None)
    if body.response_type != "code":
        raise _AuthorizationErrorRedirect(
            redirect_uri, "unsupported_response_type", "只支持 response_type=code", state
        )
    if body.code_challenge_method != "S256":
        raise _AuthorizationErrorRedirect(
            redirect_uri, "invalid_request", "必须使用 PKCE，且 code_challenge_method 只支持 S256", state
        )
    if not is_valid_code_challenge(body.code_challenge):
        raise _AuthorizationErrorRedirect(
            redirect_uri, "invalid_request", "code_challenge 缺失或格式不对", state
        )
    resource = canonical_resource(body.resource)
    if resource is None:
        raise _AuthorizationErrorRedirect(
            redirect_uri, "invalid_target", "resource 不是本站的 MCP 服务地址", state
        )
    return _ResolvedAuthorization(
        client=client,
        redirect_uri=redirect_uri,
        state=state,
        code_challenge=str(body.code_challenge),
        scopes=_granted_scopes(body.scope),
        resource=resource,
    )


@router.post("/oauth/authorize/preview", summary="MCP OAuth 同意页：校验授权请求并返回展示信息")
async def preview_authorization(
    body: AuthorizationRequestBody,
    request: Request,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: McpAccessTokenRepository = Depends(get_mcp_access_token_repository),
) -> JSONResponse:
    try:
        user_id = _user_id(current_user)
        await _enforce_limit(
            request, action="mcp_oauth.preview", identity=str(user_id), limit=_PREVIEW_PER_USER_LIMIT
        )
        resolved = await _resolve_authorization(body, repository)
    except (_OAuthFailure, _AuthorizationErrorRedirect) as failure:
        return failure.response()
    return JSONResponse(
        {
            "status": "ready",
            "client": {
                "client_id": resolved.client["client_id"],
                "client_name": resolved.client.get("client_name") or "",
                "registered_at": resolved.client.get("created_at"),
            },
            "redirect_uri": resolved.redirect_uri,
            "redirect": describe_redirect_uri(resolved.redirect_uri),
            "scopes": resolved.scopes,
            "resource": resolved.resource,
        },
        headers=_NO_STORE,
    )


@router.post("/oauth/authorize", summary="MCP OAuth 同意页：用户同意或拒绝授权")
async def decide_authorization(
    body: AuthorizationDecisionBody,
    request: Request,
    current_user: dict[str, Any] = Depends(RequireUser),
    repository: McpAccessTokenRepository = Depends(get_mcp_access_token_repository),
) -> JSONResponse:
    try:
        user_id = _user_id(current_user)
        await _enforce_limit(
            request, action="mcp_oauth.authorize", identity=str(user_id), limit=_AUTHORIZE_PER_USER_LIMIT
        )
        resolved = await _resolve_authorization(body, repository)
        if body.decision == "deny":
            denied = _AuthorizationErrorRedirect(
                resolved.redirect_uri, "access_denied", "用户拒绝了授权", resolved.state
            )
            return JSONResponse({"status": "denied", "redirect_to": denied.redirect_to}, headers=_NO_STORE)
        code = await _code_store(request).issue(
            AuthorizationCodePayload(
                client_id=resolved.client["client_id"],
                client_name=resolved.client.get("client_name") or "",
                user_id=user_id,
                redirect_uri=resolved.redirect_uri,
                code_challenge=resolved.code_challenge,
                scopes=resolved.scopes,
                resource=resolved.resource,
            )
        )
    except (_OAuthFailure, _AuthorizationErrorRedirect) as failure:
        return failure.response()
    except McpOAuthUnavailableError:
        logger.warning("[MCP OAuth] authorization code store unavailable", exc_info=True)
        return _OAuthFailure(*_UNAVAILABLE).response()
    logger.info("[MCP OAuth] user %s approved client %s", user_id, resolved.client["client_id"])
    redirect_to = redirect_with_params(
        resolved.redirect_uri, {"code": code, "state": resolved.state, "iss": MCP_OAUTH_ISSUER}
    )
    return JSONResponse({"status": "approved", "redirect_to": redirect_to}, headers=_NO_STORE)


# ---------------------------------------------------------------- token


@dataclass(frozen=True, slots=True)
class _BasicCredentials:
    client_id: str
    client_secret: str


def _basic_credentials(request: Request) -> _BasicCredentials | None:
    """解析 HTTP Basic 客户端认证；两段都先做表单解码（RFC 6749 §2.3.1）。"""
    authorization = request.headers.get("authorization", "")
    scheme, _, encoded = authorization.partition(" ")
    if scheme.lower() != "basic":
        return None
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise _OAuthFailure(
            401, "invalid_client", "Basic 认证格式不对", headers={"WWW-Authenticate": "Basic"}
        ) from exc
    client_id, separator, client_secret = decoded.partition(":")
    if not separator or not client_id:
        raise _OAuthFailure(
            401, "invalid_client", "Basic 认证格式不对", headers={"WWW-Authenticate": "Basic"}
        )
    return _BasicCredentials(unquote_plus(client_id), unquote_plus(client_secret))


async def _token_form(request: Request) -> dict[str, str]:
    form = await request.form()
    values: dict[str, str] = {}
    for name in _TOKEN_FORM_FIELDS:
        items = form.getlist(name)
        if len(items) > 1:
            raise _OAuthFailure(400, "invalid_request", f"参数 {name} 只能出现一次")
        if items and isinstance(items[0], str) and items[0] != "":
            values[name] = items[0]
    return values


async def _authenticate_client(
    request: Request,
    form: dict[str, str],
    repository: McpAccessTokenRepository,
) -> dict[str, Any]:
    basic = _basic_credentials(request)
    challenge = {"WWW-Authenticate": "Basic"} if basic else None
    body_client_id = form.get("client_id")
    if basic and body_client_id and body_client_id != basic.client_id:
        raise _OAuthFailure(400, "invalid_request", "Basic 认证与 client_id 参数不一致")
    if basic and "client_secret" in form:
        raise _OAuthFailure(400, "invalid_request", "客户端认证方式只能用一种")
    client_id = basic.client_id if basic else body_client_id
    if not client_id:
        raise _OAuthFailure(401, "invalid_client", "缺少 client_id", headers=challenge)
    client = None
    if len(client_id) <= _MAX_CLIENT_ID_LENGTH:
        client = await asyncio.to_thread(repository.get_mcp_oauth_client, client_id)
    if client is None:
        raise _OAuthFailure(401, "invalid_client", "客户端未注册或注册已失效", headers=challenge)
    if client.get("token_endpoint_auth_method") != "none":
        presented = basic.client_secret if basic else form.get("client_secret")
        if not client_secret_matches(presented, client.get("client_secret_hash")):
            raise _OAuthFailure(401, "invalid_client", "客户端认证失败", headers=challenge)
    # 公开客户端没有密钥；带了也不看，只靠 PKCE
    return client


@router.post("/oauth/token", summary="MCP OAuth 令牌端点：授权码换访问令牌")
async def exchange_token(
    request: Request,
    repository: McpAccessTokenRepository = Depends(get_mcp_access_token_repository),
) -> JSONResponse:
    try:
        await _enforce_limit(
            request,
            action="mcp_oauth.token",
            identity=client_ip_from_request(request),
            limit=_TOKEN_PER_IP_LIMIT,
        )
        form = await _token_form(request)
        grant_type = form.get("grant_type")
        if not grant_type:
            raise _OAuthFailure(400, "invalid_request", "缺少 grant_type")
        if grant_type != "authorization_code":
            raise _OAuthFailure(400, "unsupported_grant_type", "只支持 authorization_code")
        client = await _authenticate_client(request, form, repository)
        for name in ("code", "redirect_uri", "code_verifier"):
            if name not in form:
                raise _OAuthFailure(400, "invalid_request", f"缺少 {name}")
        # 先作废授权码再逐项核对：任何一项对不上，这个授权码都不能再试第二次
        payload = await _code_store(request).consume(form["code"])
        if payload is None or payload.client_id != client["client_id"]:
            raise _OAuthFailure(400, "invalid_grant", "授权码无效、已过期或已使用")
        if payload.redirect_uri != form["redirect_uri"]:
            raise _OAuthFailure(400, "invalid_grant", "redirect_uri 与授权请求不一致")
        if not verify_pkce_s256(form["code_verifier"], payload.code_challenge):
            raise _OAuthFailure(400, "invalid_grant", "PKCE 校验失败")
        if "resource" in form and canonical_resource(form["resource"]) != payload.resource:
            raise _OAuthFailure(400, "invalid_target", "resource 与授权请求不一致")
    except _OAuthFailure as failure:
        return failure.response()
    except McpOAuthUnavailableError:
        logger.warning("[MCP OAuth] authorization code store unavailable", exc_info=True)
        return _OAuthFailure(*_UNAVAILABLE).response()

    token = "aigc_mcp_" + secrets.token_urlsafe(32)
    try:
        item = await asyncio.to_thread(
            repository.create_user_mcp_token,
            user_id=payload.user_id,
            token_hash=hash_mcp_token(token),
            token_hint=f"{token[:12]}...{token[-4:]}",
            scopes=payload.scopes,
            client_type=infer_client_type(payload.client_name),
            client_label=payload.client_name or _FALLBACK_CLIENT_LABEL,
            expires_at=None,
            oauth_client_id=payload.client_id,
        )
    except ValueError:
        return _OAuthFailure(400, "invalid_grant", "授权用户不存在").response()
    logger.info(
        "[MCP OAuth] issued token to user %s via client %s (replaced %s)",
        payload.user_id,
        payload.client_id,
        item.get("replaced_count", 0),
    )
    return JSONResponse(
        {"access_token": token, "token_type": "Bearer", "scope": " ".join(payload.scopes)},
        headers=_NO_STORE,
    )
