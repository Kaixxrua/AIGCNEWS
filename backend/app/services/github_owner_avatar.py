"""Bounded, same-origin owner avatars independent of the project's cached wordmark."""
from __future__ import annotations

import hashlib
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict
from typing import Any

import httpx
from PIL import Image

from backend.app.core.config import settings
from backend.app.services.ingestion.github_artwork_transport import GitHubArtworkTransport
from backend.app.services.ingestion.github_project_logos import download_logo, resolve_owner_avatars

# Owners are shared across projects. Coalesce misses, bound memory and outbound
# concurrency, and briefly cache failures so broken owners cannot trigger a storm.
_cache: OrderedDict[str, tuple[float, dict[str, Any] | None]] = OrderedDict()
_cache_lock = threading.Lock()
_owner_locks = [threading.Lock() for _ in range(32)]
_downloads = threading.BoundedSemaphore(8)
_MAX_ENTRIES = 512


def _download(owner: str) -> dict[str, Any] | None:
    try:
        with httpx.Client(timeout=5, follow_redirects=False, trust_env=False) as api:
            url = resolve_owner_avatars([owner], api).get(owner, f"https://github.com/{owner}.png?size=128")
        with httpx.Client(
            timeout=8, follow_redirects=False, trust_env=False,
            transport=GitHubArtworkTransport(settings.github_artwork_proxy or settings.outbound_proxy or None),
        ) as images:
            content, mime = download_logo(url, images)
        return {"content": content, "content_type": mime, "sha256": hashlib.sha256(content).hexdigest()}
    except (ValueError, OSError, httpx.HTTPError, ET.ParseError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        return None


def get_owner_avatar(owner: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"[A-Za-z0-9-]{1,39}", owner):
        return None
    owner = owner.lower()
    with _owner_locks[hash(owner) % len(_owner_locks)]:
        with _cache_lock:
            cached = _cache.get(owner)
            if cached and cached[0] > time.monotonic():
                _cache.move_to_end(owner)
                return cached[1]
        if not _downloads.acquire(timeout=10):
            return None
        try:
            result = _download(owner)
        finally:
            _downloads.release()
        with _cache_lock:
            _cache[owner] = (time.monotonic() + (3600 if result else 300), result)
            _cache.move_to_end(owner)
            while len(_cache) > _MAX_ENTRIES:
                _cache.popitem(last=False)
        return result
