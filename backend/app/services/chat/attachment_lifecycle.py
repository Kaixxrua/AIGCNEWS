"""Metadata and ownership lifecycle for chat attachments."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class AttachmentType(str, Enum):
    IMAGE = "image"


class AttachmentStatus(str, Enum):
    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"
    EXPIRED = "expired"


@dataclass
class AttachmentMeta:
    """Public metadata for an owned attachment."""

    id: str
    user_id: int
    type: AttachmentType
    status: AttachmentStatus
    filename: str = ""
    mime_type: str = ""
    size_bytes: int = 0
    page_count: int = 0
    text_preview: str = ""
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    error_msg: str = ""


class AttachmentRegistry:
    """Lock-protected in-memory metadata registry with owner filtering."""

    def __init__(self, entries: Dict[str, AttachmentMeta] | None = None) -> None:
        self.entries = entries if entries is not None else {}
        self._lock = asyncio.Lock()

    async def register(self, meta: AttachmentMeta) -> None:
        async with self._lock:
            self.entries[meta.id] = meta

    async def get_owned(
        self, attachment_id: str, user_id: int
    ) -> Optional[AttachmentMeta]:
        async with self._lock:
            meta = self.entries.get(attachment_id)
            return meta if meta is not None and meta.user_id == user_id else None

    async def list_owned(
        self, attachment_ids: List[str], user_id: int
    ) -> List[AttachmentMeta]:
        result: List[AttachmentMeta] = []
        async with self._lock:
            for attachment_id in attachment_ids:
                meta = self.entries.get(attachment_id)
                if meta is not None and meta.user_id == user_id:
                    result.append(meta)
        return result


class AttachmentLifecycle:
    """Construct attachment metadata and apply its existing status transitions."""

    def __init__(
        self,
        registry: AttachmentRegistry,
        *,
        id_factory: Callable[[], object] = uuid.uuid4,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.registry = registry
        self._id_factory = id_factory
        self._clock = clock

    def new_id(self) -> str:
        return str(self._id_factory())

    async def register_image(
        self,
        *,
        attachment_id: str,
        user_id: int,
        filename: str,
        mime_type: str,
        size_bytes: int,
        expires_at: float,
    ) -> AttachmentMeta:
        meta = AttachmentMeta(
            id=attachment_id,
            user_id=user_id,
            type=AttachmentType.IMAGE,
            status=AttachmentStatus.READY,
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            created_at=self._clock(),
            expires_at=expires_at,
        )
        await self.registry.register(meta)
        return meta


    @staticmethod
    def mark_error(meta: AttachmentMeta, error_msg: str) -> None:
        meta.status = AttachmentStatus.ERROR
        meta.error_msg = error_msg
