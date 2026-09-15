"""Pure validation policy for chat attachments."""

from __future__ import annotations

import base64
import binascii
import os
import re
from dataclasses import dataclass

MAX_IMAGE_BYTES = 10 * 1024 * 1024

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


def safe_display_filename(filename: str, default: str) -> str:
    """Return a display-only basename without path or control characters."""
    normalized = (filename or "").replace("\\", "/")
    name = os.path.basename(normalized)
    name = _CONTROL_RE.sub("", name).strip().strip(".")
    if not name or name in {".", ".."}:
        return default
    return name[:255]


def image_extension(mime_type: str) -> str:
    """Return the canonical extension for an allowed image MIME type.

    仅供已通过校验的 MIME 调用（键必然存在），用于生成内容寻址文件名。
    """
    return _ALLOWED_IMAGES[mime_type][0]


def _check_image_mime(declared_mime: str) -> None:
    if declared_mime == "image/svg+xml" or declared_mime not in _ALLOWED_IMAGES:
        raise AttachmentValidationError("仅支持 JPEG、PNG、GIF 或 WebP 图片")


def _validate_image_payload(decoded: bytes, declared_mime: str, filename: str) -> ValidatedImage:
    """共享校验尾部：非空、尺寸上限、magic-byte 与 MIME 一致性。"""
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


def validate_image_bytes(
    data: bytes,
    mime_type: str,
    filename: str = "",
) -> ValidatedImage:
    """Validate raw image bytes (multipart 上传入口，与 base64 入口共享规则表)。"""
    declared_mime = (mime_type or "").strip().lower()
    _check_image_mime(declared_mime)
    return _validate_image_payload(data, declared_mime, filename)


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

    _check_image_mime(declared_mime)
    if not encoded or any(char.isspace() for char in encoded):
        raise AttachmentValidationError("图片数据格式无效")

    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise AttachmentValidationError("图片数据格式无效") from exc

    return _validate_image_payload(decoded, declared_mime, filename)


