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
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from backend.app.core.config import settings
from backend.app.services.chat.attachment_policy import ValidatedImage, ValidatedPdf


# ---------------------------------------------------------------------------
# 枚举与数据结构
# ---------------------------------------------------------------------------


class AttachmentType(str, Enum):
    IMAGE = "image"
    PDF = "pdf"


class AttachmentStatus(str, Enum):
    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    ERROR = "error"
    EXPIRED = "expired"


@dataclass
class AttachmentMeta:
    """附件元数据。"""

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
    attachment_id = str(uuid.uuid4())
    b64 = content.base64_data
    size_bytes = len(content.data)

    expire_ts = time.time() + _IMAGE_TTL

    async with _image_lock:
        await _evict_expired_images()
        _image_cache[attachment_id] = (b64, content.mime_type, expire_ts)

    meta = AttachmentMeta(
        id=attachment_id,
        user_id=user_id,
        type=AttachmentType.IMAGE,
        status=AttachmentStatus.READY,
        filename=content.filename,
        mime_type=content.mime_type,
        size_bytes=size_bytes,
        expires_at=expire_ts,
    )

    async with _registry_lock:
        _attachment_registry[attachment_id] = meta

    return meta


async def upload_pdf(
    content: ValidatedPdf,
    user_id: int,
) -> AttachmentMeta:
    """
    上传 PDF 附件：落盘 → 提取文本 → 返回附件元数据。
    """
    attachment_id = str(uuid.uuid4())
    file_path = os.path.join(_PDF_UPLOAD_DIR, f"{attachment_id}.pdf")

    meta = AttachmentMeta(
        id=attachment_id,
        user_id=user_id,
        type=AttachmentType.PDF,
        status=AttachmentStatus.PROCESSING,
        filename=content.filename,
        mime_type=content.mime_type,
        size_bytes=len(content.data),
    )

    async with _registry_lock:
        _attachment_registry[attachment_id] = meta

    # 落盘
    try:
        with open(file_path, "wb") as f:
            f.write(content.data)
    except Exception:
        meta.status = AttachmentStatus.ERROR
        meta.error_msg = "附件保存失败"
        return meta

    # 提取文本（异步包装同步 fitz 调用）
    try:
        text, page_count = await asyncio.to_thread(_extract_pdf_text, file_path)
        meta.page_count = page_count
        meta.text_preview = text[:500] if text else ""
        meta.status = AttachmentStatus.READY
    except Exception:
        meta.status = AttachmentStatus.ERROR
        meta.error_msg = "PDF 解析失败"

    return meta


async def get_attachment(
    attachment_id: str, user_id: int
) -> Optional[AttachmentMeta]:
    """获取当前用户拥有的附件元数据。"""
    async with _registry_lock:
        meta = _attachment_registry.get(attachment_id)
        return meta if meta is not None and meta.user_id == user_id else None


async def get_image_base64(
    attachment_id: str, user_id: int
) -> Optional[Tuple[str, str]]:
    """获取当前用户图片附件的 base64 和 mime_type。"""
    if await get_attachment(attachment_id, user_id) is None:
        return None
    async with _image_lock:
        entry = _image_cache.get(attachment_id)
    if entry is None or time.time() > entry[2]:
        return None
    return entry[0], entry[1]


async def get_pdf_text(attachment_id: str, user_id: int) -> Optional[str]:
    """获取当前用户 PDF 附件的全文文本。"""
    meta = await get_attachment(attachment_id, user_id)
    if meta is None or meta.type != AttachmentType.PDF:
        return None
    file_path = os.path.join(_PDF_UPLOAD_DIR, f"{attachment_id}.pdf")
    if not os.path.exists(file_path):
        return None
    try:
        text, _ = await asyncio.to_thread(_extract_pdf_text, file_path)
        return text
    except Exception:
        return None


async def list_attachments(
    attachment_ids: List[str], user_id: int
) -> List[AttachmentMeta]:
    """批量获取当前用户拥有的附件元数据。"""
    result = []
    async with _registry_lock:
        for aid in attachment_ids:
            meta = _attachment_registry.get(aid)
            if meta is not None and meta.user_id == user_id:
                result.append(meta)
    return result


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
