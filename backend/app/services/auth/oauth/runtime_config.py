"""Runtime OAuth configuration resolved from the Monitor singleton."""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from backend.app.core.config import settings
from backend.app.repositories.oauth_settings_repository import OAuthSettings, OAuthSettingsReader
from backend.app.services.auth.oauth.contracts import OAuthProviderName, parse_enabled_oauth_providers

logger = logging.getLogger(__name__)
OAuthConfigSource = Literal["database", "environment", "unconfigured"]
_CACHE_TTL_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class EffectiveOAuthConfig:
    enabled_providers: tuple[OAuthProviderName, ...]
    public_base_url: str
    github_client_id: str
    github_client_secret: str
    google_client_id: str
    google_client_secret: str
    wechat_app_id: str
    wechat_app_secret: str
    state_ttl_seconds: int
    handoff_ttl_seconds: int
    source: OAuthConfigSource
    updated_at: datetime | None = None
    qq_client_id: str = ""
    qq_client_secret: str = ""
    linuxdo_client_id: str = ""
    linuxdo_client_secret: str = ""

    @property
    def public_base_url_valid(self) -> bool:
        raw = self.public_base_url.strip().rstrip("/")
        parsed = urlsplit(raw)
        return bool(
            raw
            and parsed.scheme in {"http", "https"}
            and parsed.netloc
            and not parsed.query
            and not parsed.fragment
            and not parsed.username
            and not parsed.password
            and "\\" not in raw
        )

    def provider_configured(self, provider: OAuthProviderName) -> bool:
        if provider == "github":
            client_id, secret = self.github_client_id, self.github_client_secret
        elif provider == "google":
            client_id, secret = self.google_client_id, self.google_client_secret
        elif provider == "wechat":
            client_id, secret = self.wechat_app_id, self.wechat_app_secret
        elif provider == "qq":
            client_id, secret = self.qq_client_id, self.qq_client_secret
        elif provider == "linuxdo":
            client_id, secret = self.linuxdo_client_id, self.linuxdo_client_secret
        else:
            return False
        return bool(
            provider in self.enabled_providers
            and client_id.strip()
            and secret.strip()
            and not secret.strip().upper().startswith("CHANGEME")
        )

    @property
    def configured_providers(self) -> tuple[OAuthProviderName, ...]:
        if not self.public_base_url_valid:
            return ()
        return tuple(
            provider
            for provider in ("github", "google", "wechat", "qq", "linuxdo")
            if self.provider_configured(provider)
        )


_reader: OAuthSettingsReader | None = None
_cache: tuple[float, EffectiveOAuthConfig] | None = None
_lock = threading.Lock()


def configure_oauth_settings_reader(reader: OAuthSettingsReader | None) -> None:
    global _reader, _cache
    with _lock:
        _reader, _cache = reader, None


def invalidate_oauth_config_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def reset_oauth_config_provider() -> None:
    configure_oauth_settings_reader(None)


def _environment_config(env: object) -> EffectiveOAuthConfig:
    enabled = parse_enabled_oauth_providers(
        str(getattr(env, "oauth_enabled_providers", "") or "")
    )
    values = dict(
        enabled_providers=enabled,
        public_base_url=str(getattr(env, "public_base_url", "") or ""),
        github_client_id=str(getattr(env, "github_oauth_client_id", "") or ""),
        github_client_secret=str(getattr(env, "github_oauth_client_secret", "") or ""),
        google_client_id=str(getattr(env, "google_oauth_client_id", "") or ""),
        google_client_secret=str(getattr(env, "google_oauth_client_secret", "") or ""),
        wechat_app_id=str(getattr(env, "wechat_oauth_app_id", "") or ""),
        wechat_app_secret=str(getattr(env, "wechat_oauth_app_secret", "") or ""),
        qq_client_id=str(getattr(env, "qq_oauth_client_id", "") or ""),
        qq_client_secret=str(getattr(env, "qq_oauth_client_secret", "") or ""),
        linuxdo_client_id=str(getattr(env, "linuxdo_oauth_client_id", "") or ""),
        linuxdo_client_secret=str(getattr(env, "linuxdo_oauth_client_secret", "") or ""),
        state_ttl_seconds=int(getattr(env, "oauth_state_ttl_seconds", 300)),
        handoff_ttl_seconds=int(getattr(env, "oauth_handoff_ttl_seconds", 120)),
    )
    configured = bool(values["enabled_providers"] and values["public_base_url"])
    configured = configured or any(
        values[field]
        for field in (
            "github_client_id", "github_client_secret", "google_client_id",
            "google_client_secret", "wechat_app_id", "wechat_app_secret",
            "qq_client_id", "qq_client_secret", "linuxdo_client_id", "linuxdo_client_secret",
        )
    )
    return EffectiveOAuthConfig(
        **values,
        source="environment" if configured else "unconfigured",
    )


def effective_oauth_config_from_row(
    row: OAuthSettings,
) -> EffectiveOAuthConfig:
    return EffectiveOAuthConfig(
        enabled_providers=parse_enabled_oauth_providers(row.enabled_providers),
        public_base_url=row.public_base_url,
        github_client_id=row.github_client_id,
        github_client_secret=row.github_client_secret,
        google_client_id=row.google_client_id,
        google_client_secret=row.google_client_secret,
        wechat_app_id=row.wechat_app_id,
        wechat_app_secret=row.wechat_app_secret,
        qq_client_id=row.qq_client_id,
        qq_client_secret=row.qq_client_secret,
        linuxdo_client_id=row.linuxdo_client_id,
        linuxdo_client_secret=row.linuxdo_client_secret,
        state_ttl_seconds=int(row.state_ttl_seconds),
        handoff_ttl_seconds=int(row.handoff_ttl_seconds),
        source="database",
        updated_at=row.updated_at,
    )


def _unconfigured() -> EffectiveOAuthConfig:
    return EffectiveOAuthConfig(
        enabled_providers=(),
        public_base_url="",
        github_client_id="",
        github_client_secret="",
        google_client_id="",
        google_client_secret="",
        wechat_app_id="",
        wechat_app_secret="",
        state_ttl_seconds=300,
        handoff_ttl_seconds=120,
        source="unconfigured",
    )


def resolve_oauth_config(*, env=settings) -> EffectiveOAuthConfig:
    global _cache
    with _lock:
        # Environment values remain a compatibility/test seam and are read per
        # request. The short-lived cache is only for the bound database reader,
        # where it provides multi-worker eventual consistency without stale env
        # credentials masking runtime changes.
        if _reader is None:
            return _environment_config(env)
        if _cache is not None and time.monotonic() - _cache[0] < _CACHE_TTL_SECONDS:
            return _cache[1]

        try:
            row = _reader.get_oauth_settings()
        except Exception:
            # A bound reader means production composition is active. A missing
            # migration/table must not silently re-enable env OAuth credentials.
            logger.warning(
                "[OAuth] 读取 oauth_settings 失败，OAuth fail-closed",
                exc_info=True,
            )
            config = _unconfigured()
        else:
            config = (
                effective_oauth_config_from_row(row)
                if row is not None
                else _environment_config(env)
            )

        _cache = (time.monotonic(), config)
        return config
