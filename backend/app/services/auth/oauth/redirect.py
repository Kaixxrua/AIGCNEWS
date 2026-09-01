"""Canonical and internal-only redirect validation for OAuth flows."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit, urlunsplit

from backend.app.services.auth.oauth.runtime_config import EffectiveOAuthConfig, resolve_oauth_config

OAUTH_CALLBACK_PATH = "/api/auth/oauth/{provider}/callback"
OAUTH_FRONTEND_CALLBACK_PATH = "/oauth/callback"
# 绑定等账户操作的前端回跳路径：与游客登录回调分离，避免绑定产物
# 误入登录 consume 流程
OAUTH_FRONTEND_ACTION_CALLBACK_PATH = "/oauth/action-callback"


class OAuthRedirectError(ValueError):
    """Raised when a redirect is external, malformed, or unsafe."""


def safe_internal_redirect(value: str | None) -> str:
    raw = value or "/"
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in raw):
        raise OAuthRedirectError("redirect contains control characters")
    candidate = raw.strip()
    if not candidate:
        raise OAuthRedirectError("redirect contains control characters")
    if candidate.startswith("//") or not candidate.startswith("/"):
        raise OAuthRedirectError("redirect must be an internal path")
    decoded = unquote(candidate)
    if "\\" in decoded or "%2f" in candidate.lower() or "%5c" in candidate.lower():
        raise OAuthRedirectError("redirect contains an encoded authority bypass")
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise OAuthRedirectError("redirect must not contain an origin")
    if parsed.path != candidate.split("?", 1)[0].split("#", 1)[0]:
        raise OAuthRedirectError("redirect path is malformed")
    return urlunsplit(("", "", parsed.path or "/", parsed.query, parsed.fragment))


def canonical_base_url(config: EffectiveOAuthConfig | None = None) -> str:
    effective = config or resolve_oauth_config()
    raw = effective.public_base_url.strip().rstrip("/")
    parsed = urlsplit(raw)
    if not effective.public_base_url_valid:
        raise OAuthRedirectError("PUBLIC_BASE_URL is not configured")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise OAuthRedirectError("PUBLIC_BASE_URL is not configured")
    return raw


def canonical_frontend_callback_uri(config: EffectiveOAuthConfig | None = None) -> str:
    return f"{canonical_base_url(config)}{OAUTH_FRONTEND_CALLBACK_PATH}"


def canonical_frontend_action_callback_uri(config: EffectiveOAuthConfig | None = None) -> str:
    return f"{canonical_base_url(config)}{OAUTH_FRONTEND_ACTION_CALLBACK_PATH}"


def canonical_callback_uri(
    provider: str,
    config: EffectiveOAuthConfig | None = None,
) -> str:
    if provider not in {"github", "google", "wechat"}:
        raise OAuthRedirectError("unknown OAuth provider")
    return f"{canonical_base_url(config)}{OAUTH_CALLBACK_PATH.format(provider=provider)}"
