from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TelegramSettings:
    """Singleton Telegram push configuration with decrypted secrets in memory only."""

    enabled: bool
    bot_token: str
    bot_username: str
    webhook_secret: str
    link_ttl_seconds: int = 300
    request_timeout_seconds: float = 5.0
    updated_at: datetime | None = None


class TelegramSettingsReader(Protocol):
    def get_telegram_settings(self) -> TelegramSettings | None: ...


class TelegramSettingsManager(TelegramSettingsReader, Protocol):
    def upsert_telegram_settings(
        self,
        *,
        enabled: bool,
        bot_token: str,
        bot_username: str,
        webhook_secret: str,
        link_ttl_seconds: int,
        request_timeout_seconds: float,
    ) -> TelegramSettings: ...

    def delete_telegram_settings(self) -> int: ...


class TelegramSettingsRepository(TelegramSettingsManager, Protocol):
    """Persistence boundary for the singleton Monitor-managed Telegram settings."""
