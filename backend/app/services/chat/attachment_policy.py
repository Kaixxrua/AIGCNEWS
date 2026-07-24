"""Pure validation policy for chat attachments."""

from __future__ import annotations

import base64
import binascii
import os
import re
from dataclasses import dataclass

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_PDF_BYTES = 50 * 1024 * 1024

_ALLOWED_IMAGES = {
    "image/jpeg": (".jpg", lambda data: data.startswith(b"\xff\xd8\xff")),
    "image/png": (".png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
    "image/gif": (
        ".gif",
        lambda data: data.startswith((b"GIF87a", b"GIF89a")),
    ),
    "image/webp": (
        ".webp",
        lambda data: len(data) >= 12
        and data.startswith(b"RIFF")
        and data[8:12] == b"WEBP",
    ),
}
_DATA_URI_RE = re.compile(r"\Adata:([^;,]+);base64,([^\r\n]*)\Z", re.IGNORECASE)
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class AttachmentValidationError(ValueError):
    """A validation failure with a safe, client-facing message."""


@dataclass(frozen=True)
class ValidatedImage:
    data: bytes
    base64_data: str
    mime_type: str
    filename: str


@dataclass(frozen=True)
class ValidatedPdf:
    data: bytes
    filename: str
    mime_type: str = "application/pdf"


def safe_display_filename(filename: str, default: str) -> str:
    """Return a display-only basename without path or control characters."""
    normalized = (filename or "").replace("\\", "/")
    name = os.path.basename(normalized)
    name = _CONTROL_RE.sub("", name).strip().strip(".")
    if not name or name in {".", ".."}:
        return default
    return name[:255]


def validate_image_attachment(
    base64_data: str,
    mime_type: str,
    filename: str = "",
) -> ValidatedImage:
    """Strictly decode and validate a supported raster image."""
    declared_mime = (mime_type or "").strip().lower()
    encoded = base64_data
    match = _DATA_URI_RE.fullmatch(base64_data)
    if base64_data.lower().startswith("data:"):
        if match is None:
            raise AttachmentValidationError("图片数据格式无效")
        uri_mime = match.group(1).lower()
        if uri_mime != declared_mime:
            raise AttachmentValidationError("图片 MIME 类型不匹配")
        encoded = match.group(2)

    if declared_mime == "image/svg+xml" or declared_mime not in _ALLOWED_IMAGES:
        raise AttachmentValidationError("仅支持 JPEG、PNG、GIF 或 WebP 图片")
    if not encoded or any(char.isspace() for char in encoded):
        raise AttachmentValidationError("图片数据格式无效")

    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise AttachmentValidationError("图片数据格式无效") from exc

    if not decoded:
        raise AttachmentValidationError("图片数据格式无效")
    if len(decoded) > MAX_IMAGE_BYTES:
        raise AttachmentValidationError("图片大小不能超过 10 MiB")

    extension, signature_matches = _ALLOWED_IMAGES[declared_mime]
    if not signature_matches(decoded):
        raise AttachmentValidationError("图片内容与 MIME 类型不匹配")

    return ValidatedImage(
        data=decoded,
        base64_data=base64.b64encode(decoded).decode("ascii"),
        mime_type=declared_mime,
        filename=safe_display_filename(filename, f"image{extension}"),
    )


def validate_pdf_attachment(file_bytes: bytes, filename: str = "") -> ValidatedPdf:
    """Validate PDF size and magic bytes and sanitize its display name."""
    if len(file_bytes) > MAX_PDF_BYTES:
        raise AttachmentValidationError("PDF 文件大小不能超过 50 MiB")
    if not file_bytes.startswith(b"%PDF-"):
        raise AttachmentValidationError("PDF 文件内容无效")
    return ValidatedPdf(
        data=file_bytes,
        filename=safe_display_filename(filename, "upload.pdf"),
    )
