"""Browser-mediated OAuth routes.

Provider adapters are an intentionally optional integration point: until an adapter is
composed, every provider route fails closed rather than pretending OAuth is enabled.

登录（login）与账户绑定（bind）共用同一 provider 回调路径，但两者在四个层面
互相隔离：

1. state/handoff 的 Redis 键空间分离（``auth:oauth:bind:*``）；
2. state/handoff 载荷模型分离（绑定专用模型，跨操作重放在模型层被拒）；
3. 绑定 handoff 使用独立 cookie（``aigc_oauth_bind_handoff``）；
4. 绑定回调绝不调用 resolve_first_login、绝不创建/合并账户、绝不签发登录令牌。
"""
from __future__ import annotations

import asyncio
import hmac
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from backend.app.api.dependencies import (
    get_oauth_identity_repository,
    get_user_account_repository,
)
from backend.app.core.auth import RequireUser, create_access_token, extract_user_id
from backend.app.models.schema_oauth import (
    OAuthBindConsumeResponse,
    OAuthBindHandoffPayload,
    OAuthCallbackQuery,
    OAuthConsumeResponse,
    OAuthHandoffPayload,
    OAuthStartQuery,
    OAuthStatePayload,
)
from backend.app.repositories.oauth_identity_repository import OAuthIdentityRepository
from backend.app.repositories.user_account_repository import UserAccountRepository
from backend.app.services.auth.oauth.contracts import (
    OAuthAdapterUnavailable,
    OAuthProviderAdapter,
)
from backend.app.services.auth.oauth.handoff import (
    OAUTH_BIND_HANDOFF_PREFIX,
    OAuthHandoffInvalidError,
    OAuthHandoffStore,
    OAuthHandoffUnavailableError,
)
from backend.app.services.auth.oauth.providers.github import GitHubOAuthError
from backend.app.services.auth.oauth.providers.google import GoogleOAuthError
from backend.app.services.auth.oauth.providers.wechat import WeChatOAuthError
from backend.app.services.auth.oauth.redirect import (
    OAuthRedirectError,
    canonical_callback_uri,
    canonical_frontend_action_callback_uri,
    canonical_frontend_callback_uri,
    safe_internal_redirect,
)
from backend.app.services.auth.oauth.registry import configured_oauth_providers
from backend.app.services.auth.oauth.service import (
    build_oauth_adapters,
    pkce_challenge,
)
from backend.app.services.auth.oauth.state import (
    OAUTH_BIND_STATE_PREFIX,
    OAuthStateInvalidError,
    OAuthStateStore,
    OAuthStateUnavailableError,
    create_state_material,
    digest_secret,
)

logger = logging.getLogger(__name__)
router = APIRouter()
_BROWSER_COOKIE = "aigc_oauth_browser"
_BIND_HANDOFF_COOKIE = "aigc_oauth_bind_handoff"
_COOKIE_MAX_AGE = 900


def _config(request: Request):
    from backend.app.services.auth.oauth.runtime_config import resolve_oauth_config

    return resolve_oauth_config()


def _stores(request: Request, config) -> tuple[OAuthStateStore, OAuthHandoffStore]:
    redis = getattr(request.app.state, "redis", None)
    return (
        OAuthStateStore(redis, ttl_seconds=config.state_ttl_seconds),
        OAuthHandoffStore(redis, ttl_seconds=config.handoff_ttl_seconds),
    )


def _bind_stores(request: Request, config) -> tuple[OAuthStateStore, OAuthHandoffStore]:
    redis = getattr(request.app.state, "redis", None)
    return (
        OAuthStateStore(
            redis, ttl_seconds=config.state_ttl_seconds, prefix=OAUTH_BIND_STATE_PREFIX
        ),
        OAuthHandoffStore(
            redis,
            ttl_seconds=config.handoff_ttl_seconds,
            prefix=OAUTH_BIND_HANDOFF_PREFIX,
            model=OAuthBindHandoffPayload,
        ),
    )


def _adapter(request: Request, provider: str, config) -> OAuthProviderAdapter:
    redis_available = getattr(request.app.state, "redis", None) is not None
    if provider not in configured_oauth_providers(
        redis_available=redis_available,
        config=config,
    ):
        raise HTTPException(status_code=503, detail="oauth_provider_unavailable")
    adapter = build_oauth_adapters(config).get(provider)
    if adapter is None:
        raise HTTPException(status_code=503, detail="oauth_provider_unavailable")
    return adapter


def _binding(request: Request, response: Response) -> str:
    value = request.cookies.get(_BROWSER_COOKIE)
    if value and len(value) <= 256:
        return value
    import secrets
    value = secrets.token_urlsafe(32)
    response.set_cookie(
        _BROWSER_COOKIE, value, max_age=_COOKIE_MAX_AGE, httponly=True,
        secure=True, samesite="lax", path="/",
    )
    return value


def _binding_matches(request: Request, expected_hash: str) -> bool:
    actual = request.cookies.get(_BROWSER_COOKIE, "")
    return bool(actual) and hmac.compare_digest(digest_secret(actual), expected_hash)


def _current_user_id(current_user: dict) -> int:
    user_id = extract_user_id(current_user)
    if user_id is None or user_id <= 0:
        raise HTTPException(status_code=401, detail="oauth_account_invalid")
    return user_id


@router.get("/auth/oauth/{provider}/start", summary="Start OAuth login")
async def oauth_start(provider: str, request: Request, query: OAuthStartQuery = Depends()):
    provider = provider.strip().lower()
    config = _config(request)
    adapter = _adapter(request, provider, config)
    try:
        redirect_to = safe_internal_redirect(query.redirect_to)
    except OAuthRedirectError as exc:
        raise HTTPException(status_code=400, detail="oauth_redirect_invalid") from exc
    response = Response()
    binding = _binding(request, response)
    material = create_state_material(use_pkce=adapter.use_pkce, use_nonce=adapter.use_nonce)
    state_payload = OAuthStatePayload(
        provider=provider, redirect_to=redirect_to, pkce_verifier=material.code_verifier,
        nonce=material.nonce, browser_binding_hash=digest_secret(binding),
    )
    states, _ = _stores(request, config)
    try:
        callback_uri = canonical_callback_uri(provider, config)
        url = adapter.authorization_url(
            state=material.state, redirect_uri=callback_uri,
            code_challenge=pkce_challenge(material.code_verifier) if material.code_verifier else None,
            nonce=material.nonce,
        )
        await states.put(material, state_payload)
    except (OAuthStateUnavailableError, OAuthAdapterUnavailable, OAuthRedirectError) as exc:
        raise HTTPException(status_code=503, detail="oauth_unavailable") from exc
    result = RedirectResponse(url, status_code=307)
    if response.headers.get("set-cookie"):
        result.headers["set-cookie"] = response.headers["set-cookie"]
    return result


@router.get("/auth/oauth/{provider}/bind/start", summary="Start OAuth account binding")
async def oauth_bind_start(
    provider: str,
    request: Request,
    query: OAuthStartQuery = Depends(),
    current_user: dict = Depends(RequireUser),
):
    """已认证用户发起渠道绑定：目标账户只写入服务端 state，不出现在 URL 中。"""
    provider = provider.strip().lower()
    target_user_id = _current_user_id(current_user)
    config = _config(request)
    adapter = _adapter(request, provider, config)
    try:
        redirect_to = safe_internal_redirect(query.redirect_to)
    except OAuthRedirectError as exc:
        raise HTTPException(status_code=400, detail="oauth_redirect_invalid") from exc
    response = Response()
    binding = _binding(request, response)
    material = create_state_material(use_pkce=adapter.use_pkce, use_nonce=adapter.use_nonce)
    state_payload = OAuthStatePayload(
        provider=provider, redirect_to=redirect_to, pkce_verifier=material.code_verifier,
        nonce=material.nonce, browser_binding_hash=digest_secret(binding),
        operation="bind", target_user_id=target_user_id,
    )
    states, _ = _bind_stores(request, config)
    try:
        # 复用与登录相同的 provider 回调地址：provider 控制台无需新增 redirect URI，
        # 回调内按 state.operation 分流
        callback_uri = canonical_callback_uri(provider, config)
        url = adapter.authorization_url(
            state=material.state, redirect_uri=callback_uri,
            code_challenge=pkce_challenge(material.code_verifier) if material.code_verifier else None,
            nonce=material.nonce,
        )
        await states.put(material, state_payload)
    except (OAuthStateUnavailableError, OAuthAdapterUnavailable, OAuthRedirectError) as exc:
        raise HTTPException(status_code=503, detail="oauth_unavailable") from exc
    result = RedirectResponse(url, status_code=307)
    if response.headers.get("set-cookie"):
        result.headers["set-cookie"] = response.headers["set-cookie"]
    return result


async def _oauth_callback_login(
    *,
    provider: str,
    state: OAuthStatePayload,
    code: str,
    adapter: OAuthProviderAdapter,
    config,
    identities: OAuthIdentityRepository,
    handoffs: OAuthHandoffStore,
) -> RedirectResponse:
    """游客登录分支：解析/创建账户并签发登录 handoff。"""
    try:
        profile = await adapter.exchange_code(
            code=code, redirect_uri=canonical_callback_uri(provider, config),
            code_verifier=state.pkce_verifier, nonce=state.nonce,
        )
        resolution = await asyncio.to_thread(
            identities.resolve_first_login, provider=provider,
            provider_subject=profile.provider_subject, display_email=profile.email,
            email_verified=profile.email_verified, username=profile.username,
        )
        user = resolution.user
        if not user:
            raise HTTPException(status_code=401, detail="oauth_login_failed")
        if user.get("disabled"):
            raise HTTPException(status_code=401, detail="oauth_account_disabled")
        token = await handoffs.put(OAuthHandoffPayload(
            user_id=int(user["id"]), redirect_to=state.redirect_to,
            browser_binding_hash=state.browser_binding_hash,
        ))
    except HTTPException:
        raise
    except (GitHubOAuthError, GoogleOAuthError, WeChatOAuthError) as exc:
        # 三个 provider 的异常消息均为固定 reason code（已核查不含 token/上游
        # 原始响应），记录 reason 便于线上定位，不回传给浏览器。
        logger.warning(
            "OAuth callback failed: provider=%s reason=%s",
            provider, str(exc) or type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail="oauth_callback_failed") from exc
    except (OAuthAdapterUnavailable, OAuthHandoffUnavailableError, OAuthRedirectError) as exc:
        raise HTTPException(status_code=503, detail="oauth_unavailable") from exc
    target = canonical_frontend_callback_uri(config)
    result = RedirectResponse(target, status_code=303)
    result.set_cookie(
        "aigc_oauth_handoff", token, max_age=config.handoff_ttl_seconds,
        httponly=True, secure=True, samesite="lax", path="/",
    )
    return result


async def _oauth_callback_bind(
    *,
    provider: str,
    state: OAuthStatePayload,
    code: str,
    adapter: OAuthProviderAdapter,
    config,
    identities: OAuthIdentityRepository,
    users: UserAccountRepository,
    handoffs: OAuthHandoffStore,
) -> RedirectResponse:
    """账户绑定分支：只写身份关系到 state 指定的目标账户，绝不建号/合并/签发令牌。"""
    target_user_id = int(state.target_user_id or 0)
    if target_user_id <= 0:
        raise HTTPException(status_code=400, detail="oauth_state_invalid")
    target_user = await asyncio.to_thread(users.get_user_by_id, target_user_id)
    if not target_user:
        raise HTTPException(status_code=401, detail="oauth_account_invalid")
    if target_user.get("disabled"):
        raise HTTPException(status_code=401, detail="oauth_account_disabled")
    try:
        profile = await adapter.exchange_code(
            code=code, redirect_uri=canonical_callback_uri(provider, config),
            code_verifier=state.pkce_verifier, nonce=state.nonce,
        )
        bind_result = await asyncio.to_thread(
            identities.bind_identity,
            user_id=target_user_id, provider=provider,
            provider_subject=profile.provider_subject, display_email=profile.email,
            email_verified=profile.email_verified,
        )
        if bind_result.status == "owned_by_other":
            raise HTTPException(status_code=409, detail="oauth_identity_conflict")
        token = await handoffs.put(OAuthBindHandoffPayload(
            user_id=target_user_id, provider=provider, status=bind_result.status,
            redirect_to=state.redirect_to,
            browser_binding_hash=state.browser_binding_hash,
        ))
    except HTTPException:
        raise
    except (GitHubOAuthError, GoogleOAuthError, WeChatOAuthError) as exc:
        logger.warning(
            "OAuth bind callback failed: provider=%s reason=%s",
            provider, str(exc) or type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail="oauth_callback_failed") from exc
    except (OAuthAdapterUnavailable, OAuthHandoffUnavailableError, OAuthRedirectError) as exc:
        raise HTTPException(status_code=503, detail="oauth_unavailable") from exc
    target = canonical_frontend_action_callback_uri(config)
    result = RedirectResponse(target, status_code=303)
    result.set_cookie(
        _BIND_HANDOFF_COOKIE, token, max_age=config.handoff_ttl_seconds,
        httponly=True, secure=True, samesite="lax", path="/",
    )
    return result


@router.get("/auth/oauth/{provider}/callback", summary="OAuth callback")
async def oauth_callback(
    provider: str, request: Request, response: Response,
    query: OAuthCallbackQuery = Depends(),
    identities: OAuthIdentityRepository = Depends(get_oauth_identity_repository),
    users: UserAccountRepository = Depends(get_user_account_repository),
):
    provider = provider.strip().lower()
    config = _config(request)
    if query.error:
        raise HTTPException(status_code=400, detail="oauth_authorization_failed")
    adapter = _adapter(request, provider, config)
    # state 的命名空间由载荷判别决定前的第一次消费：先按登录空间尝试，
    # 再按绑定空间尝试——两个空间的键互不重叠，同一 opaque state 只可能
    # 存在于其一，且一次性消费保证无法被另一空间重放。
    login_states, login_handoffs = _stores(request, config)
    bind_states, bind_handoffs = _bind_stores(request, config)
    state: OAuthStatePayload | None = None
    consumed_as_bind = False
    try:
        state = await login_states.consume(query.state)
    except (OAuthStateInvalidError, OAuthStateUnavailableError):
        try:
            state = await bind_states.consume(query.state)
            consumed_as_bind = True
        except (OAuthStateInvalidError, OAuthStateUnavailableError) as exc:
            raise HTTPException(status_code=400, detail="oauth_state_invalid") from exc
    # 命名空间与载荷判别必须一致：任何不一致都按无效 state 拒绝
    if consumed_as_bind != (state.operation == "bind"):
        raise HTTPException(status_code=400, detail="oauth_state_invalid")
    if state.provider != provider or not _binding_matches(request, state.browser_binding_hash):
        raise HTTPException(status_code=400, detail="oauth_state_invalid")
    if state.operation == "bind":
        return await _oauth_callback_bind(
            provider=provider, state=state, code=query.code, adapter=adapter,
            config=config, identities=identities, users=users,
            handoffs=bind_handoffs,
        )
    return await _oauth_callback_login(
        provider=provider, state=state, code=query.code, adapter=adapter,
        config=config, identities=identities, handoffs=login_handoffs,
    )


@router.post("/auth/oauth/consume", response_model=OAuthConsumeResponse, summary="Consume OAuth handoff")
async def oauth_consume(
    request: Request,
    response: Response,
    repository: UserAccountRepository = Depends(get_user_account_repository),
):
    config = _config(request)
    _, handoffs = _stores(request, config)
    handoff = request.cookies.get("aigc_oauth_handoff", "")
    try:
        payload = await handoffs.consume(handoff)
    except (OAuthHandoffInvalidError, OAuthHandoffUnavailableError) as exc:
        raise HTTPException(status_code=400, detail="oauth_handoff_invalid") from exc
    if not _binding_matches(request, payload.browser_binding_hash):
        raise HTTPException(status_code=400, detail="oauth_handoff_invalid")
    user = await asyncio.to_thread(repository.get_user_by_id, payload.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="oauth_login_failed")
    if user.get("disabled"):
        raise HTTPException(status_code=401, detail="oauth_account_disabled")
    token = create_access_token({
        "user_id": int(user["id"]), "role": user.get("role") or "user",
        "email": user.get("email"), "pwd_ver": int(user.get("pwd_ver") or 1),
    })
    response.headers["Cache-Control"] = "no-store"
    response.delete_cookie("aigc_oauth_handoff", path="/")
    response.delete_cookie(_BROWSER_COOKIE, path="/")
    return OAuthConsumeResponse(
        access_token=token, role=str(user.get("role") or "user"),
        redirect_to=safe_internal_redirect(payload.redirect_to),
    )


@router.post(
    "/auth/oauth/bind/consume",
    response_model=OAuthBindConsumeResponse,
    summary="Consume OAuth binding handoff",
)
async def oauth_bind_consume(
    request: Request,
    response: Response,
    current_user: dict = Depends(RequireUser),
):
    """完成账户绑定：只回显绑定结果，绝不签发或轮换会话令牌。

    handoff 一次性消费；载荷中的目标账户必须与当前已认证用户一致，
    防止他人浏览器的绑定产物被本会话冒领。
    """
    current_user_id = _current_user_id(current_user)
    config = _config(request)
    _, handoffs = _bind_stores(request, config)
    handoff = request.cookies.get(_BIND_HANDOFF_COOKIE, "")
    try:
        payload = await handoffs.consume(handoff)
    except (OAuthHandoffInvalidError, OAuthHandoffUnavailableError) as exc:
        raise HTTPException(status_code=400, detail="oauth_handoff_invalid") from exc
    if not isinstance(payload, OAuthBindHandoffPayload):
        raise HTTPException(status_code=400, detail="oauth_handoff_invalid")
    if payload.user_id != current_user_id:
        raise HTTPException(status_code=400, detail="oauth_handoff_invalid")
    if not _binding_matches(request, payload.browser_binding_hash):
        raise HTTPException(status_code=400, detail="oauth_handoff_invalid")
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.delete_cookie(_BIND_HANDOFF_COOKIE, path="/")
    response.delete_cookie(_BROWSER_COOKIE, path="/")
    return OAuthBindConsumeResponse(
        provider=payload.provider, status=payload.status,
        redirect_to=safe_internal_redirect(payload.redirect_to),
    )
