from __future__ import annotations

from backend.app.services.auth.oauth.contracts import (
    OAUTH_PROVIDERS,
    OAuthProviderConfig,
    OAuthProviderName,
)
from backend.app.services.auth.oauth.runtime_config import resolve_oauth_config


def _provider_config(
    name: OAuthProviderName,
    *,
    config=None,
) -> OAuthProviderConfig:
    effective = config or resolve_oauth_config()
    if name == "github":
        return OAuthProviderConfig(
            name=name,
            client_id=effective.github_client_id,
            client_secret=effective.github_client_secret,
        )
    if name == "google":
        return OAuthProviderConfig(
            name=name,
            client_id=effective.google_client_id,
            client_secret=effective.google_client_secret,
        )
    return OAuthProviderConfig(
        name=name,
        client_id=effective.wechat_app_id,
        client_secret=effective.wechat_app_secret,
    )


def configured_oauth_providers(
    *,
    redis_available: bool = True,
    config=None,
) -> list[str]:
    """Return only providers safe to expose to clients."""
    if not redis_available:
        return []
    effective = config or resolve_oauth_config()
    return list(effective.configured_providers)


def get_oauth_provider_config(
    name: str,
    *,
    config=None,
) -> OAuthProviderConfig | None:
    normalized = name.strip().lower()
    if normalized not in OAUTH_PROVIDERS:
        return None
    provider = _provider_config(normalized, config=config)  # type: ignore[arg-type]
    effective = config or resolve_oauth_config()
    if normalized not in effective.configured_providers:
        return None
    return provider
