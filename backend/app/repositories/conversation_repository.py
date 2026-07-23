from __future__ import annotations

from typing import Any, Protocol


class ConversationReader(Protocol):
    """Read user-owned conversations without exposing cross-user rows."""

    def get_owned_conversation_context(
        self,
        *,
        user_id: int,
        conversation_id: int,
    ) -> dict[str, Any] | None: ...

    def list_conversations(
        self,
        *,
        user_id: int,
        scope: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]: ...


class ConversationWriter(Protocol):
    """Create, retain, and delete user-owned conversations."""

    def ensure_conversation(
        self,
        *,
        user_id: int,
        scope: str = "global",
        scope_key: str | None = None,
        title: str | None = None,
        keep_latest: int = 10,
    ) -> dict[str, Any]: ...

    def create_conversation(
        self,
        *,
        user_id: int,
        scope: str = "global",
        scope_key: str | None = None,
        title: str | None = None,
        keep_latest: int = 10,
    ) -> dict[str, Any]: ...

    def delete_owned_conversation(
        self,
        *,
        user_id: int,
        conversation_id: int,
    ) -> bool: ...


class ConversationMessageWriter(Protocol):
    """Apply owner-scoped message mutations as atomic operations."""

    def append_message_pair(
        self,
        *,
        user_id: int,
        conversation_id: int | None,
        scope: str,
        scope_key: str | None,
        user_message: str,
        assistant_content: str,
        assistant_thinking: str = "",
        sources: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        parent_message_id: int | None = None,
        title: str | None = None,
        max_messages: int = 10,
        max_conversations: int = 10,
    ) -> dict[str, Any]: ...

    def delete_owned_message_branch(
        self,
        *,
        user_id: int,
        message_id: int,
    ) -> dict[str, Any] | None: ...

    def prepare_owned_regeneration(
        self,
        *,
        user_id: int,
        message_id: int,
    ) -> dict[str, Any] | None: ...


class ConversationQuotaReader(Protocol):
    """Read retained user-message usage for the current CST calendar day."""

    def count_user_messages_today(self, user_id: int) -> int: ...


class ConversationCleanupWriter(Protocol):
    """Delete a bounded oldest-first batch of stale conversations."""

    def cleanup_stale_conversations(
        self,
        *,
        stale_days: int = 7,
        limit: int = 5,
    ) -> int: ...


class ConversationRepository(
    ConversationReader,
    ConversationWriter,
    ConversationMessageWriter,
    ConversationQuotaReader,
    ConversationCleanupWriter,
    Protocol,
):
    """Combined owner-scoped conversation, message, quota, and cleanup boundary."""
