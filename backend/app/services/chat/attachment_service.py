"""
附件上传与管理服务。

支持两种附件类型：
  - image: 图片（base64 存 Redis，TTL 10min）
  - pdf:   本地 PDF（落盘 + 文本提取 + 可选向量切片）

设计约束：
  - 图片沿用 Zero-Disk 策略，仅存内存/Redis
  - PDF 落盘到临时安全目录，提取文本后存入 MySQL chat_attachments 表
  - 每个附件有唯一 attachment_id（UUID4）
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import time
import uuid
from typing import Dict, List, Optional, Tuple

from backend.app.core.config import settings
from backend.app.services.chat.attachment_lifecycle import (
    AttachmentLifecycle,
    AttachmentMeta,
    AttachmentRegistry,
    AttachmentStatus,
    AttachmentType,
)
from backend.app.services.chat.attachment_policy import ValidatedImage, ValidatedPdf
from backend.app.services.chat.attachment_storage import ImageCache, PdfStorage


# ---------------------------------------------------------------------------
# 图片内存缓存（与 routes_vision.py 兼容，但使用独立缓存）
# ---------------------------------------------------------------------------

_IMAGE_TTL = 600  # 10 分钟
_image_cache: Dict[str, Tuple[str, str, float]] = {}  # {id: (base64, mime, expire_ts)}
_image_lock = asyncio.Lock()


async def _evict_expired_images() -> None:
    now = time.time()
    expired = [k for k, (_, _, ts) in _image_cache.items() if ts < now]
    for k in expired:
        del _image_cache[k]


# ---------------------------------------------------------------------------
# PDF 临时存储目录
# ---------------------------------------------------------------------------

_PDF_UPLOAD_DIR = os.path.join(
    getattr(settings, "papers_storage_dir", "storage/papers"),
    "_chat_uploads",
)
os.makedirs(_PDF_UPLOAD_DIR, exist_ok=True)

# 附件元数据注册表（内存，生产环境应改为 Redis/MySQL）
_attachment_registry: Dict[str, AttachmentMeta] = {}
_registry_lock = asyncio.Lock()
_image_store = ImageCache(clock=lambda: time.time())
_image_store._entries = _image_cache
_attachment_store = AttachmentRegistry(_attachment_registry)
_attachment_lifecycle = AttachmentLifecycle(
    _attachment_store,
    id_factory=lambda: uuid.uuid4(),
    clock=lambda: time.time(),
)


def _pdf_storage() -> PdfStorage:
    return PdfStorage(_PDF_UPLOAD_DIR, extractor=_extract_pdf_text)


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
        return meta

    try:
        text, page_count = await storage.extract_text(attachment_id)
        _attachment_lifecycle.mark_pdf_ready(meta, text, page_count)
    except Exception:
        _attachment_lifecycle.mark_error(meta, "PDF 解析失败")

    return meta


async def get_attachment(
    attachment_id: str, user_id: int
) -> Optional[AttachmentMeta]:
    """获取当前用户拥有的附件元数据。"""
    return await _attachment_store.get_owned(attachment_id, user_id)


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
    return await _attachment_store.list_owned(attachment_ids, user_id)


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def _extract_pdf_text(file_path: str) -> Tuple[str, int]:
    """
    使用 PyMuPDF (fitz) 提取 PDF 全文文本。
    返回 (full_text, page_count)。
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        # fitz 不可用时，返回空文本
        return "", 0

    doc = fitz.open(file_path)
    page_count = len(doc)
    text_parts: List[str] = []
    for page in doc:
        text_parts.append(page.get_text())
    doc.close()
    return "\n".join(text_parts), page_count
