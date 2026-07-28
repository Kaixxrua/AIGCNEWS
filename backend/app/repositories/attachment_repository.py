from __future__ import annotations

from typing import Any, Protocol


class AttachmentRepository(Protocol):
    """Owner-scoped persistence for chat attachment metadata."""

    def create_chat_attachment(
        self,
        *,
        user_id: int,
        conversation_id: int | None,
        file_name: str,
        mime_type: str,
        modality: str,
        storage_path: str | None = None,
        file_size: int = 0,
        page_count: int | None = None,
        parse_status: str = "uploaded",
        extract_text: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def get_chat_attachment(
        self,
        attachment_id: int,
        *,
        user_id: int | None = None,
    ) -> dict[str, Any] | None: ...

    def list_chat_attachments(
        self,
        *,
        user_id: int,
        conversation_id: int | None = None,
    ) -> list[dict[str, Any]]: ...
