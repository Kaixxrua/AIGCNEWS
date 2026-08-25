from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


class TelegramLinkAttemptRepository(Protocol):
    """Owner-scoped, single-use Telegram deep-link attempts."""

    def create_attempt(
        self,
        *,
        attempt_id: UUID,
        user_id: int,
        nonce_hash: str,
        expires_at: datetime,
    ) -> dict[str, Any]: ...

    def get_attempt(self, *, user_id: int, attempt_id: UUID) -> dict[str, Any] | None: ...

    def consume_attempt(
        self,
        *,
        nonce_hash: str,
        chat_id: str,
    ) -> dict[str, Any] | None: ...

    def attach_channel(self, *, attempt_id: UUID, channel_id: int) -> None: ...
