from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID


class WeChatLoginAttemptRepository(Protocol):
    """Persistence boundary for owner-scoped QR login attempts."""

    def create_login_attempt(
        self,
        owner_id: int,
        attempt_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def get_login_attempt(
        self,
        owner_id: int,
        attempt_id: UUID,
    ) -> dict[str, Any] | None: ...

    def update_login_attempt(
        self,
        owner_id: int,
        attempt_id: UUID,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None: ...

    def delete_login_attempt(self, owner_id: int, attempt_id: UUID) -> bool: ...

    def expire_login_attempts(self, owner_id: int) -> int: ...


class WeChatSessionRepository(Protocol):
    """Persistence boundary for encrypted, owner-scoped WeChat sessions."""

    def get_wechat_session(self, owner_id: int) -> dict[str, Any] | None: ...

    def save_wechat_session(
        self,
        owner_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def mark_wechat_session_invalid(
        self,
        owner_id: int,
        reason_code: str,
    ) -> dict[str, Any] | None: ...

    def delete_wechat_session(self, owner_id: int) -> bool: ...
