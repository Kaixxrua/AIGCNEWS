"""Provider-neutral OAuth adapter contracts and request-time composition."""
from __future__ import annotations

import base64
import hashlib

from backend.app.services.auth.oauth.contracts import (
    OAuthProviderAdapter,
    OAuthProviderConfig,
)
from backend.app.services.auth.oauth.providers.github import (
    GitHubOAuthConfig,
    GitHubOAuthProvider,
)
from backend.app.services.auth.oauth.providers.google import GoogleOIDCProvider
from backend.app.services.auth.oauth.providers.linuxdo import LinuxDOOAuthProvider
from backend.app.services.auth.oauth.providers.qq import QQOAuthProvider
from backend.app.services.auth.oauth.providers.wechat import WeChatOAuthProvider
from backend.app.services.auth.oauth.runtime_config import EffectiveOAuthConfig, resolve_oauth_config


def build_oauth_adapters(
    config: EffectiveOAuthConfig | None = None,
) -> dict[str, OAuthProviderAdapter]:
    """Build adapters from one immutable request-time configuration snapshot."""
    effective = config or resolve_oauth_config()
    adapters: dict[str, OAuthProviderAdapter] = {}
    if effective.provider_configured("github"):
        adapters["github"] = GitHubOAuthProvider(
            GitHubOAuthConfig(effective.github_client_id, effective.github_client_secret)
        )  # type: ignore[assignment]
    if effective.provider_configured("google"):
        adapters["google"] = GoogleOIDCProvider(
            OAuthProviderConfig("google", effective.google_client_id, effective.google_client_secret)
        )  # type: ignore[assignment]
    if effective.provider_configured("wechat"):
        adapters["wechat"] = WeChatOAuthProvider(
            OAuthProviderConfig("wechat", effective.wechat_app_id, effective.wechat_app_secret)
        )  # type: ignore[assignment]
    if effective.provider_configured("qq"):
        adapters["qq"] = QQOAuthProvider(
            OAuthProviderConfig("qq", effective.qq_client_id, effective.qq_client_secret)
        )
    if effective.provider_configured("linuxdo"):
        adapters["linuxdo"] = LinuxDOOAuthProvider(
            OAuthProviderConfig("linuxdo", effective.linuxdo_client_id, effective.linuxdo_client_secret)
        )
    return adapters


def pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
