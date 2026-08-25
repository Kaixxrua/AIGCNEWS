"""Browser-mediated OAuth routes.

Provider adapters are an intentionally optional integration point: until an adapter is
composed, every provider route fails closed rather than pretending OAuth is enabled.
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
from backend.app.core.auth import create_access_token
from backend.app.models.schema_oauth import (
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
    canonical_frontend_callback_uri,
    safe_internal_redirect,
)
from backend.app.services.auth.oauth.registry import configured_oauth_providers
from backend.app.services.auth.oauth.service import (
    build_oauth_adapters,
    pkce_challenge,
)
from backend.app.services.auth.oauth.state import (
    OAuthStateInvalidError,
    OAuthStateStore,
    OAuthStateUnavailableError,
    create_state_material,
    digest_secret,
)

logger = logging.getLogger(__name__)
router = APIRouter()
_BROWSER_COOKIE = "aigc_oauth_browser"
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


@router.get("/auth/oauth/{provider}/callback", summary="OAuth callback")
async def oauth_callback(
    provider: str, request: Request, response: Response,
    query: OAuthCallbackQuery = Depends(),
    identities: OAuthIdentityRepository = Depends(get_oauth_identity_repository),
):
    provider = provider.strip().lower()
    config = _config(request)
    if query.error:
        raise HTTPException(status_code=400, detail="oauth_authorization_failed")
    adapter = _adapter(request, provider, config)
    states, handoffs = _stores(request, config)
    try:
        state = await states.consume(query.state)
    except (OAuthStateInvalidError, OAuthStateUnavailableError) as exc:
        raise HTTPException(status_code=400, detail="oauth_state_invalid") from exc
    if state.provider != provider or not _binding_matches(request, state.browser_binding_hash):
        raise HTTPException(status_code=400, detail="oauth_state_invalid")
    try:
        profile = await adapter.exchange_code(
            code=query.code, redirect_uri=canonical_callback_uri(provider, config),
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
