"""Canonical and internal-only redirect validation for OAuth flows."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit, urlunsplit

from backend.app.core.config import settings
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


def alternate_base_urls() -> tuple[str, ...]:
    """备用登录入口白名单（设置层已校验为小写、无尾斜杠的 https origin）。"""
    raw = str(getattr(settings, "oauth_alternate_base_urls", "") or "")
    return tuple(item for item in raw.split(",") if item)


def alternate_entry_for_forwarded_host(
    forwarded_host: str | None,
    config: EffectiveOAuthConfig | None = None,
) -> str | None:
    """边缘 X-Forwarded-Host 精确命中白名单主机时返回该备用入口，否则 None（走 canonical）。

    头值只用于在白名单内做选择，永不参与 URL 拼接；空值、多值、带端口或未知主机
    一律回落 canonical。即便被直连伪造，也只会让发起者自己的流程在 provider 回调
    校验或 host-only 浏览器绑定 cookie 上失败。
    """
    host = (forwarded_host or "").strip().lower()
    if not host or "," in host:
        return None
    canonical = canonical_base_url(config).lower()
    for entry in alternate_base_urls():
        if entry != canonical and urlsplit(entry).netloc == host:
            return entry
    return None


def entry_base_url(entry: str | None, config: EffectiveOAuthConfig | None = None) -> str:
    """把 state 记录的入口还原为本次流程的 base；已移出白名单的入口 fail closed。"""
    if entry is None:
        return canonical_base_url(config)
    if entry not in alternate_base_urls():
        raise OAuthRedirectError("OAuth entry is no longer an allowed alternate base URL")
    return entry


def provider_callback_uri(provider: str, base_url: str) -> str:
    if provider not in {"github", "google", "wechat"}:
        raise OAuthRedirectError("unknown OAuth provider")
    return f"{base_url}{OAUTH_CALLBACK_PATH.format(provider=provider)}"


def frontend_callback_uri(base_url: str) -> str:
    return f"{base_url}{OAUTH_FRONTEND_CALLBACK_PATH}"


def frontend_action_callback_uri(base_url: str) -> str:
    return f"{base_url}{OAUTH_FRONTEND_ACTION_CALLBACK_PATH}"


def canonical_frontend_callback_uri(config: EffectiveOAuthConfig | None = None) -> str:
    return frontend_callback_uri(canonical_base_url(config))


def canonical_frontend_action_callback_uri(config: EffectiveOAuthConfig | None = None) -> str:
    return frontend_action_callback_uri(canonical_base_url(config))


def canonical_callback_uri(
    provider: str,
    config: EffectiveOAuthConfig | None = None,
) -> str:
    if provider not in {"github", "google", "wechat"}:
        raise OAuthRedirectError("unknown OAuth provider")
    return provider_callback_uri(provider, canonical_base_url(config))
