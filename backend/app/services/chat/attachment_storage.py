"""Storage adapters for chat attachments."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections.abc import Callable
from typing import Dict, List, Optional, Tuple

from backend.app.core.config import settings

IMAGE_TTL_SECONDS = 600

# 私有聊天附件必须落在 /api/media/papers 匿名静态挂载树之外：
# StaticFiles 不做任何鉴权，放在 papers_storage_dir 下的文件任何人可匿名下载，
# 会绕过 GET /api/chat/attachments/{id} 的属主校验（capability-URL 不是访问控制）。
LEGACY_PDF_UPLOAD_DIR = os.path.join(
    getattr(settings, "papers_storage_dir", "storage/papers"),
    "_chat_uploads",
)
DEFAULT_PDF_UPLOAD_DIR = getattr(
    settings, "chat_uploads_storage_dir", "storage/chat_uploads"
)

logger = logging.getLogger(__name__)

try:
    os.makedirs(DEFAULT_PDF_UPLOAD_DIR, exist_ok=True)
except OSError:
    # 尽力而为：开发机/只读环境下目录可能不可建，写入侧（PdfStorage.write）
    # 仍会按需创建；容器部署经 compose volume 预建并属主 1000。
    logger.warning(
        "[Attachment] 附件目录预建失败（写入时重试）: %s",
        DEFAULT_PDF_UPLOAD_DIR,
        exc_info=True,
    )


def migrate_legacy_pdf_uploads(
    legacy_dir: str = LEGACY_PDF_UPLOAD_DIR,
    target_dir: str = DEFAULT_PDF_UPLOAD_DIR,
) -> int:
    """把历史版本中落在公开挂载树里的附件迁入私有目录，返回迁移文件数。

    旧版本把私有 PDF 写在 papers_storage_dir/_chat_uploads 下（匿名可下载），
    升级后原目录不再有读取方；残留文件迁走后尝试删除空目录，彻底切断匿名路径。
    尽力而为：单个文件失败仅记录日志，不阻断启动。
    """
    moved = 0
    if os.path.abspath(legacy_dir) == os.path.abspath(target_dir):
        return moved
    try:
        names = os.listdir(legacy_dir)
    except OSError:
        return moved
    try:
        os.makedirs(target_dir, exist_ok=True)
    except OSError:
        logger.warning(
            "[Attachment] 历史附件迁移目标目录不可建: %s", target_dir, exc_info=True
        )
        return moved
    for name in names:
        if not name.endswith(".pdf"):
            continue
        src = os.path.join(legacy_dir, name)
        dst = os.path.join(target_dir, name)
        try:
            if os.path.exists(dst):
                os.remove(src)
            else:
                os.replace(src, dst)
            moved += 1
        except OSError:
            logger.warning("[Attachment] 历史附件迁移失败: %s", src, exc_info=True)
    if moved:
        logger.info("[Attachment] 已从公开挂载目录迁出 %d 个历史附件", moved)
    try:
        os.rmdir(legacy_dir)
    except OSError:
        pass
    return moved


migrate_legacy_pdf_uploads()

ImageEntry = Tuple[str, str, float]
PdfText = Tuple[str, int]


class ImageCache:
    """Owner-agnostic in-memory cache for validated image payloads."""

    def __init__(
        self,
        *,
        ttl_seconds: int = IMAGE_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._entries: Dict[str, ImageEntry] = {}
        self._lock = asyncio.Lock()

    async def put(self, attachment_id: str, base64_data: str, mime_type: str) -> float:
        now = self._clock()
        expires_at = now + self._ttl_seconds
        async with self._lock:
            expired = [
                key for key, (_, _, entry_expiry) in self._entries.items()
                if entry_expiry < now
            ]
            for key in expired:
                del self._entries[key]
            self._entries[attachment_id] = (base64_data, mime_type, expires_at)
        return expires_at

    async def get(self, attachment_id: str) -> Optional[Tuple[str, str]]:
        async with self._lock:
            entry = self._entries.get(attachment_id)
        if entry is None or self._clock() > entry[2]:
            return None
        return entry[0], entry[1]


class PdfStorage:
    """Local PDF storage with synchronous writes and threaded text extraction."""

    def __init__(
        self,
        upload_dir: str = DEFAULT_PDF_UPLOAD_DIR,
        *,
        extractor: Callable[[str], PdfText] | None = None,
    ) -> None:
        self.upload_dir = upload_dir
        self._extractor = extractor or extract_pdf_text

    def path_for(self, attachment_id: str) -> str:
        return os.path.join(self.upload_dir, f"{attachment_id}.pdf")

    def write(self, attachment_id: str, data: bytes) -> None:
        os.makedirs(self.upload_dir, exist_ok=True)
        with open(self.path_for(attachment_id), "wb") as file:
            file.write(data)

    def exists(self, attachment_id: str) -> bool:
        return os.path.exists(self.path_for(attachment_id))

    async def extract_text(self, attachment_id: str) -> PdfText:
        return await asyncio.to_thread(self._extractor, self.path_for(attachment_id))


def extract_pdf_text(file_path: str) -> PdfText:
    """Extract full PDF text in document order with PyMuPDF."""
    try:
        import fitz  # PyMuPDF
    except ImportError:
        return "", 0

    doc = fitz.open(file_path)
    page_count = len(doc)
    text_parts: List[str] = []
    for page in doc:
        text_parts.append(page.get_text())
    doc.close()
    return "\n".join(text_parts), page_count
