"""Pure allow-listing for content exposed at public serialization boundaries."""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import urlsplit

_MARKDOWN_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_UNSAFE_RESOURCE = re.compile(
    r"(?<![\w])(?:"
    r"file://[^\s<>]*|javascript:[^\s<>]*|data:[^\s<>]*|ftp://[^\s<>]*|"
    r"(?<!:)//[^\s<>]*|/home/[^\s<>]*|/tmp/[^\s<>]*|/var/[^\s<>]*|"
    r"/etc/[^\s<>]*|/root/[^\s<>]*|storage/[^\s<>]*|"
    r"[A-Za-z]:[\\/][^\s<>]*|\\\\[^\s<>]*|"
    r"/[^\s<>]*\.\.?/[^\s<>]*)",
    re.IGNORECASE,
)


def sanitize_public_resource_url(value: str) -> str | None:
    candidate = unescape(str(value or "")).strip()
    if not candidate or any(ord(char) < 0x20 for char in candidate):
        return None
    if "\\" in candidate or candidate.startswith("//"):
        return None
    parts = urlsplit(candidate)
    if parts.scheme.lower() == "https":
        if not parts.netloc or parts.username or parts.password:
            return None
        if ".." in [part for part in parts.path.split("/") if part]:
            return None
        return candidate
    if parts.scheme or not candidate.startswith("/api/media/"):
        return None
    if ".." in [part for part in parts.path.split("/") if part]:
        return None
    return candidate


def sanitize_public_text(value: str) -> str:
    text = str(value or "")

    def replace_image(match: re.Match[str]) -> str:
        return match.group(0) if sanitize_public_resource_url(match.group(2)) else ""

    def replace_link(match: re.Match[str]) -> str:
        return match.group(0) if sanitize_public_resource_url(match.group(2)) else match.group(1)

    text = _MARKDOWN_IMAGE.sub(replace_image, text)
    text = _MARKDOWN_LINK.sub(replace_link, text)
    return _UNSAFE_RESOURCE.sub("", text)
