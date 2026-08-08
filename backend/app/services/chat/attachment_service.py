"""
附件上传与管理服务。

支持两种附件类型：
  - image: 图片（base64 存 Redis，TTL 10min）
  - pdf:   本地 PDF（落盘 + 文本提取 + 可选向量切片）

设计约束：
  - 图片沿用 Zero-Disk 策略，仅存内存/Redis
  - PDF 落盘到临时安全目录，提取文本后存入 PostgreSQL
  - 每个附件有唯一 attachment_id（UUID4）
  - 附件元数据持久化到 PostgreSQL chat_attachment_meta 表
    （替代原进程内内存字典，重启/多 worker 可见）
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Dict, List, Optional, Tuple

from backend.app.core.config import settings
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
from backend.app.services.chat.attachment_policy import ValidatedImage, ValidatedPdf
from backend.app.services.chat.attachment_storage import (
    ImageCache,
    PdfStorage,
    extract_pdf_text,
)

logger = logging.getLogger(__name__)

# Public compatibility view used by existing tests and in-process callers.
_image_cache: Dict[str, Tuple[str, str, float]] = {}


# ---------------------------------------------------------------------------
# PDF 临时存储目录
# ---------------------------------------------------------------------------

_PDF_UPLOAD_DIR = os.path.join(
    getattr(settings, "papers_storage_dir", "storage/papers"),
    "_chat_uploads",
)
os.makedirs(_PDF_UPLOAD_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# 附件元数据持久化（PostgreSQL）
# ---------------------------------------------------------------------------


def _meta_storage_path(meta: AttachmentMeta) -> Optional[str]:
    if meta.type != AttachmentType.PDF:
        return None
    return _pdf_storage().path_for(meta.id)


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
        "storage_path": _meta_storage_path(meta),
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
        return _meta_from_row(row) if row is not None else None

    async def list_owned(
        self, attachment_ids: List[str], user_id: int
    ) -> List[AttachmentMeta]:
        rows = await asyncio.to_thread(
            self._repository.list_attachment_meta, list(attachment_ids), user_id=user_id
        )
        return [_meta_from_row(row) for row in rows]


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


def _pdf_storage() -> PdfStorage:
    return PdfStorage(_PDF_UPLOAD_DIR, extractor=extract_pdf_text)


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


async def upload_pdf(
    content: ValidatedPdf,
    user_id: int,
) -> AttachmentMeta:
    """
    上传 PDF 附件：落盘 → 提取文本 → 返回附件元数据。
    """
    attachment_id = _attachment_lifecycle.new_id()
    meta = await _attachment_lifecycle.register_pdf(
        attachment_id=attachment_id,
        user_id=user_id,
        filename=content.filename,
        mime_type=content.mime_type,
        size_bytes=len(content.data),
    )
    storage = _pdf_storage()

    try:
        storage.write(attachment_id, content.data)
    except Exception:
        _attachment_lifecycle.mark_error(meta, "附件保存失败")
        await _meta_store.save(meta)
        return meta

    try:
        text, page_count = await storage.extract_text(attachment_id)
        _attachment_lifecycle.mark_pdf_ready(meta, text, page_count)
    except Exception:
        _attachment_lifecycle.mark_error(meta, "PDF 解析失败")
    await _meta_store.save(meta)

    return meta


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


async def get_pdf_text(attachment_id: str, user_id: int) -> Optional[str]:
    """获取当前用户 PDF 附件的全文文本。"""
    meta = await get_attachment(attachment_id, user_id)
    if meta is None or meta.type != AttachmentType.PDF:
        return None
    storage = _pdf_storage()
    if not storage.exists(attachment_id):
        return None
    try:
        text, _ = await storage.extract_text(attachment_id)
        return text
    except Exception:
        return None


async def list_attachments(
    attachment_ids: List[str], user_id: int
) -> List[AttachmentMeta]:
    """批量获取当前用户拥有的附件元数据。"""
    return await _meta_store.list_owned(attachment_ids, user_id)


# ---------------------------------------------------------------------------
# 启动对账
# ---------------------------------------------------------------------------


def reconcile_orphan_attachments(
    *,
    now: Optional[float] = None,
    upload_dir: Optional[str] = None,
) -> Dict[str, int]:
    """启动对账：清理无元数据的孤儿 PDF 文件与 TTL 到期的元数据行。

    最小可用策略：
      1. 扫描 PDF 上传目录，删除 chat_attachment_meta 中无对应行的文件；
      2. 删除 expires_at 已过期（> 0 且 < now）的元数据行（当前为图片附件）。
    返回清理计数，调用方负责记录日志。
    """
    now_ts = time.time() if now is None else now
    directory = _PDF_UPLOAD_DIR if upload_dir is None else upload_dir

    orphan_files_removed = 0
    if os.path.isdir(directory):
        disk_ids = [
            name[: -len(".pdf")]
            for name in os.listdir(directory)
            if name.endswith(".pdf")
        ]
        if disk_ids:
            existing = _meta_repository.existing_attachment_ids(disk_ids)
            for attachment_id in disk_ids:
                if attachment_id in existing:
                    continue
                try:
                    os.remove(os.path.join(directory, f"{attachment_id}.pdf"))
                    orphan_files_removed += 1
                except OSError as exc:
                    logger.warning(
                        "[Attachment] 删除孤儿附件文件失败 %s: %s", attachment_id, exc
                    )

    expired_rows_removed = _meta_repository.delete_expired_attachment_meta(now_ts)
    logger.info(
        "[Attachment] 孤儿对账完成：删除孤儿文件 %d 个，过期元数据 %d 行",
        orphan_files_removed,
        expired_rows_removed,
    )
    return {
        "orphan_files_removed": orphan_files_removed,
        "expired_rows_removed": expired_rows_removed,
    }
