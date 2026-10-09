from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class OAuthSettings:
    """Singleton OAuth application configuration with decrypted secrets in memory only."""

    enabled_providers: str
    public_base_url: str
    github_client_id: str
    github_client_secret: str
    google_client_id: str
    google_client_secret: str
    wechat_app_id: str
    wechat_app_secret: str
    state_ttl_seconds: int = 300
    handoff_ttl_seconds: int = 120
    updated_at: datetime | None = None
    qq_client_id: str = ""
    qq_client_secret: str = ""
    linuxdo_client_id: str = ""
    linuxdo_client_secret: str = ""


class OAuthSettingsReader(Protocol):
    def get_oauth_settings(self) -> OAuthSettings | None: ...


class OAuthSettingsManager(OAuthSettingsReader, Protocol):
    def upsert_oauth_settings(
        self,
        *,
        enabled_providers: str,
        public_base_url: str,
        github_client_id: str,
        github_client_secret: str,
        google_client_id: str,
        google_client_secret: str,
        wechat_app_id: str,
        wechat_app_secret: str,
        state_ttl_seconds: int,
        handoff_ttl_seconds: int,
        qq_client_id: str = "",
        qq_client_secret: str = "",
        linuxdo_client_id: str = "",
        linuxdo_client_secret: str = "",
    ) -> OAuthSettings: ...

    def delete_oauth_settings(self) -> int: ...


class OAuthSettingsRepository(OAuthSettingsManager, Protocol):
    """Persistence boundary for the singleton Monitor-managed OAuth settings."""
