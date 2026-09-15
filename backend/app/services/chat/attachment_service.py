"""
附件上传与管理服务。

支持图片附件（base64 存内存，TTL 10min）。

设计约束：
  - 图片沿用 Zero-Disk 策略，仅存内存/Redis
  - 每个附件有唯一 attachment_id（UUID4）
  - 附件元数据持久化到 PostgreSQL chat_attachment_meta 表
    （替代原进程内内存字典，重启/多 worker 可见）
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Dict, List, Optional, Tuple

from backend.app.core.postgres_database import postgres_database
from backend.app.repositories.postgres_attachment_meta_repository import (
    PostgresAttachmentMetaRepository,
)

# 公共门面再导出：routes_chat 惰性导入与既有测试均以本模块为访问点。
from backend.app.services.chat.attachment_lifecycle import (
    AttachmentLifecycle,
    AttachmentMeta,
    AttachmentRegistry as AttachmentRegistry,
    AttachmentStatus as AttachmentStatus,
    AttachmentType,
)
from backend.app.services.chat.attachment_policy import ValidatedImage
from backend.app.services.chat.attachment_storage import ImageCache

logger = logging.getLogger(__name__)

# Public compatibility view used by existing tests and in-process callers.
_image_cache: Dict[str, Tuple[str, str, float]] = {}


def _meta_to_row(meta: AttachmentMeta) -> dict:
    return {
        "attachment_id": meta.id,
        "user_id": meta.user_id,
        "attachment_type": meta.type.value,
        "status": meta.status.value,
        "file_name": meta.filename,
        "mime_type": meta.mime_type,
        "size_bytes": meta.size_bytes,
        "page_count": meta.page_count,
        "text_preview": meta.text_preview,
        "storage_path": None,
        "error_msg": meta.error_msg,
        "created_at": meta.created_at,
        "expires_at": meta.expires_at,
    }


def _meta_from_row(row: dict) -> AttachmentMeta:
    return AttachmentMeta(
        id=str(row["attachment_id"]),
        user_id=int(row["user_id"]),
        type=AttachmentType(str(row["attachment_type"])),
        status=AttachmentStatus(str(row["status"])),
        filename=str(row.get("file_name") or ""),
        mime_type=str(row.get("mime_type") or ""),
        size_bytes=int(row.get("size_bytes") or 0),
        page_count=int(row.get("page_count") or 0),
        text_preview=str(row.get("text_preview") or ""),
        created_at=float(row["created_at"]),
        expires_at=float(row.get("expires_at") or 0.0),
        error_msg=str(row.get("error_msg") or ""),
    )


class _PostgresMetaStore:
    """Async adapter binding AttachmentMeta to chat_attachment_meta rows."""

    def __init__(self, repository: PostgresAttachmentMetaRepository) -> None:
        self._repository = repository

    async def register(self, meta: AttachmentMeta) -> None:
        await self.save(meta)

    async def save(self, meta: AttachmentMeta) -> None:
        await asyncio.to_thread(
            self._repository.upsert_attachment_meta, **_meta_to_row(meta)
        )

    async def get_owned(
        self, attachment_id: str, user_id: int
    ) -> Optional[AttachmentMeta]:
        row = await asyncio.to_thread(
            self._repository.get_attachment_meta, attachment_id, user_id=user_id
        )
        return _meta_from_row(row) if row is not None and row["attachment_type"] == "image" else None

    async def list_owned(
        self, attachment_ids: List[str], user_id: int
    ) -> List[AttachmentMeta]:
        rows = await asyncio.to_thread(
            self._repository.list_attachment_meta, list(attachment_ids), user_id=user_id
        )
        return [_meta_from_row(row) for row in rows if row["attachment_type"] == "image"]


class _MetaStoreRegistry:
    """Registry facade forwarding lifecycle registrations to the meta store.

    Reads the module-level ``_meta_store`` at call time so tests can substitute
    an in-memory implementation via ``patch.object``.
    """

    async def register(self, meta: AttachmentMeta) -> None:
        await _meta_store.register(meta)


_image_store = ImageCache(clock=lambda: time.time())
_image_store._entries = _image_cache
_meta_repository = PostgresAttachmentMetaRepository(postgres_database)
_meta_store = _PostgresMetaStore(_meta_repository)
_attachment_lifecycle = AttachmentLifecycle(
    _MetaStoreRegistry(),
    id_factory=lambda: uuid.uuid4(),
    clock=lambda: time.time(),
)


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------


async def upload_image(
    content: ValidatedImage,
    user_id: int,
) -> AttachmentMeta:
    """
    上传图片附件，存入内存缓存，返回附件元数据。
    """
    attachment_id = _attachment_lifecycle.new_id()
    expire_ts = await _image_store.put(
        attachment_id, content.base64_data, content.mime_type
    )
    return await _attachment_lifecycle.register_image(
        attachment_id=attachment_id,
        user_id=user_id,
        filename=content.filename,
        mime_type=content.mime_type,
        size_bytes=len(content.data),
        expires_at=expire_ts,
    )


async def get_attachment(
    attachment_id: str, user_id: int
) -> Optional[AttachmentMeta]:
    """获取当前用户拥有的附件元数据。"""
    return await _meta_store.get_owned(attachment_id, user_id)


async def get_image_base64(
    attachment_id: str, user_id: int
) -> Optional[Tuple[str, str]]:
    """获取当前用户图片附件的 base64 和 mime_type。"""
    if await get_attachment(attachment_id, user_id) is None:
        return None
    return await _image_store.get(attachment_id)


async def list_attachments(
    attachment_ids: List[str], user_id: int
) -> List[AttachmentMeta]:
    """批量获取当前用户拥有的附件元数据。"""
    return await _meta_store.list_owned(attachment_ids, user_id)


# ---------------------------------------------------------------------------
# 启动对账
# ---------------------------------------------------------------------------


def reconcile_orphan_attachments(*, now: Optional[float] = None) -> Dict[str, int]:
    """Expire attachment metadata without reading or deleting historical files."""
    now_ts = time.time() if now is None else now
    return {
        "orphan_files_removed": 0,
        "expired_rows_removed": _meta_repository.delete_expired_attachment_meta(now_ts),
    }
