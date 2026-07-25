"""Storage adapters for chat attachments."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from typing import Dict, List, Optional, Tuple

from backend.app.core.config import settings

IMAGE_TTL_SECONDS = 600
DEFAULT_PDF_UPLOAD_DIR = os.path.join(
    getattr(settings, "papers_storage_dir", "storage/papers"),
    "_chat_uploads",
)
os.makedirs(DEFAULT_PDF_UPLOAD_DIR, exist_ok=True)

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
