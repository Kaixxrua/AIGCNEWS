"""Conservative README logo discovery and bounded durable artwork ingestion.

Repository text is untrusted data. Never execute instructions, forward GitHub
credentials to image hosts, or mistake the first screenshot/badge for a logo.
"""
from __future__ import annotations

import hashlib
import io
import re
import threading
import time
import warnings
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from PIL import Image

from backend.app.core.config import settings
from backend.app.core.github_artwork import GITHUB_DEFAULT_AVATAR_SHA256
from backend.app.services.ingestion.github_artwork_transport import ARTWORK_HOSTS, GitHubArtworkTransport
from backend.app.services.outbound_target_policy import normalize_http_url, pin_http_target

MAX_DOWNLOAD = 1_000_000
MAX_STORED = 262144
_REPO = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9_.-]+$")
_LOGO = re.compile(r"(?:^|[^a-z])(logo|logomark|wordmark|icon)(?:[^a-z]|$)", re.I)
_EXCLUDE = re.compile(r"badge|shield|sponsor|visitor|star-history|screenshot|open.?graph", re.I)
_SVG_TAGS = {"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline",
             "polygon", "defs", "linearGradient", "radialGradient", "stop", "title", "desc"}
_SVG_ATTRS = {"viewBox", "width", "height", "x", "y", "x1", "x2", "y1", "y2", "cx",
              "cy", "r", "rx", "ry", "d", "points", "fill", "fill-rule", "fill-opacity",
              "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-opacity",
              "opacity", "transform", "id", "offset", "stop-color", "stop-opacity",
              "gradientUnits", "gradientTransform", "fx", "fy", "preserveAspectRatio"}


def logo_url(raw: str, base: str) -> str:
    url = normalize_http_url(urljoin(base, raw), allowed_ports={443})
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ARTWORK_HOSTS:
        raise ValueError("unsupported artwork host")
    if parts.hostname == "github.com":
        if re.fullmatch(r"/[A-Za-z0-9-]+\.png", parts.path):
            return url
        if "/blob/" not in parts.path and "/raw/" not in parts.path:
            raise ValueError("not a GitHub file URL")
        url = url.replace("https://github.com/", "https://raw.githubusercontent.com/", 1)
        url = url.replace("/blob/", "/", 1).replace("/raw/", "/", 1)
    return url


def discover_logos(markdown: str, download_url: str) -> tuple[str, ...]:
    if not download_url:
        return ()
    # Ignore code examples and images late in the document (sponsors/tutorials).
    text = re.sub(r"```[\s\S]*?```", "", markdown[:40_000])
    candidates = [(m.group(1), m.group(2)) for m in re.finditer(
        r"!\[([^\]]*)\]\(<?([^\s)>]+)>?(?:\s+[^)]*)?\)", text)]
    soup = BeautifulSoup(text, "html.parser")
    candidates += [(str(tag.get("alt") or ""), str(tag.get("src") or "")) for tag in soup.find_all("img")]
    found: list[str] = []
    for alt, source in candidates:
        try:
            evidence = f"{alt} {urlsplit(source).path}"
            if not _LOGO.search(evidence) or _EXCLUDE.search(evidence):
                continue
            url = logo_url(source, download_url)
        except ValueError:
            continue
        if url not in found:
            found.append(url)
    return tuple(found[:4])


def sanitize_image(body: bytes) -> tuple[bytes, str]:
    if not body or len(body) > MAX_DOWNLOAD:
        raise ValueError("invalid image size")
    if b"<svg" in body[:1024].lower():
        if len(body) > MAX_STORED or re.search(br"<!\s*(DOCTYPE|ENTITY)", body, re.I):
            raise ValueError("unsafe SVG declaration")
        root = ET.fromstring(body)
        if root.tag.rsplit("}", 1)[-1] != "svg":
            raise ValueError("not SVG")
        # Reject active/unknown nodes rather than serving partially altered artwork.
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1] not in _SVG_TAGS:
                raise ValueError("unsupported SVG element")
            for name, value in list(node.attrib.items()):
                if name not in _SVG_ATTRS:
                    del node.attrib[name]
                    continue
                if re.search(r"url\s*\(", value, re.I) and not re.fullmatch(r"url\(#[\w-]+\)", value):
                    raise ValueError("external SVG reference")
        ET.register_namespace("", "http://www.w3.org/2000/svg")
        sanitized = ET.tostring(root, encoding="utf-8")
        if len(sanitized) > MAX_STORED:
            raise ValueError("SVG too large")
        return sanitized, "image/svg+xml"
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(body)) as image:
            if image.width * image.height > 4_000_000:
                raise ValueError("image dimensions too large")
            image.seek(0)
            image.thumbnail((256, 256))
            output = io.BytesIO()
            image.convert("RGBA").save(output, format="WEBP", quality=90)
    result = output.getvalue()
    if len(result) > MAX_STORED:
        raise ValueError("image too large")
    return result, "image/webp"


def download_logo(url: str, client: httpx.Client) -> tuple[bytes, str]:
    # DNS pinning uses the existing SSRF policy, including when a proxy is used.
    safe = logo_url(url, url)
    target = pin_http_target(safe, reject_mixed=True, allowed_ports={443})
    return _download_pinned_logo(target, client)


def _download_pinned_logo(target: Any, client: httpx.Client) -> tuple[bytes, str]:
    with client.stream("GET", target.request_url, headers=target.headers,
                       extensions=target.extensions, follow_redirects=False) as response:
        # Only the official owner-avatar entry point may redirect, and only once
        # to a numeric avatar ID. The second hop is independently validated/pinned.
        if (target.headers.get("Host") == "github.com"
                and re.fullmatch(r"/[A-Za-z0-9-]+\.png", urlsplit(target.request_url).path)
                and response.status_code in {301, 302, 303, 307, 308}):
            location = response.headers.get("location", "")
            safe = logo_url(location, location)
            parts = urlsplit(safe)
            if parts.hostname != "avatars.githubusercontent.com" or not re.fullmatch(r"/u/[0-9]+", parts.path):
                raise ValueError("unsupported avatar redirect")
            return download_logo(safe, client)
        response.raise_for_status()
        if response.status_code != 200:
            raise ValueError("artwork redirects are not followed")
        chunks = bytearray()
        for chunk in response.iter_bytes():
            chunks.extend(chunk)
            if len(chunks) > MAX_DOWNLOAD:
                raise ValueError("artwork too large")
        content, content_type = sanitize_image(bytes(chunks))
        if hashlib.sha256(content).hexdigest() == GITHUB_DEFAULT_AVATAR_SHA256:
            raise ValueError("GitHub default avatar is not project artwork")
        return content, content_type


def collect_logo(
    full_name: str, api_client: httpx.Client, image_client: httpx.Client, readme_enabled: bool = True,
) -> dict[str, Any]:
    from backend.app.services.ingestion.source_github import fetch_github_readme_snapshot

    if not _REPO.fullmatch(full_name):
        return {"status": "failed"}
    snapshot = fetch_github_readme_snapshot(full_name, api_client) if readme_enabled else None
    rate_limited = snapshot is not None and snapshot.status == "rate_limited"
    candidates = snapshot.logo_candidates if snapshot and snapshot.status == "succeeded" else ()
    # Cache the owner avatar too: browsers must not depend on GitHub connectivity.
    avatar = f"https://github.com/{full_name.split('/')[0]}.png?size=128"
    errors = []
    for url in (*candidates, avatar):
        try:
            content, content_type = download_logo(url, image_client)
            return {"status": "found", "source_url": url, "content": content,
                    "content_type": content_type, "sha256": hashlib.sha256(content).hexdigest(),
                    "readme_rate_limited": rate_limited}
        except (ValueError, httpx.HTTPError, OSError, ET.ParseError,
                Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            errors.append({"host": urlsplit(url).hostname, "error": type(exc).__name__, "http_status": status})
    return {"status": "failed", "readme_rate_limited": rate_limited, "errors": errors}


def refresh_project_logos(
    repository: Any, *, limit: int = 100, interval: float = 1.0, max_seconds: float = 300,
    workers: int = 4,
) -> dict[str, int]:
    # limit=0 drains the due queue within the time budget. Deferred rows remain durable.
    counts = {"selected": 0, "found": 0, "not_found": 0, "failed": 0, "rate_limited": 0}
    deadline = time.monotonic() + max_seconds
    readme_limited = threading.Event()
    with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as api, httpx.Client(
        timeout=15, follow_redirects=False, trust_env=False,
        transport=GitHubArtworkTransport(proxy=settings.outbound_proxy or None),
    ) as images, ThreadPoolExecutor(max_workers=max(1, min(workers, 16))) as pool:
        def collect(row):
            if time.monotonic() >= deadline:
                return None
            result = collect_logo(row["full_name"], api, images, not readme_limited.is_set())
            if result.get("readme_rate_limited"):
                readme_limited.set()
            time.sleep(max(0.0, interval))
            return row, result

        while True:
            remaining = max(0, limit - counts["selected"]) if limit else 100
            rows = repository.pending(min(remaining, 100))
            if not rows:
                break
            attempted = 0
            for item in pool.map(collect, rows):
                if item is None:
                    continue
                row, result = item
                repository.save(row["repo_id"], result)
                counts["selected"] += 1
                counts[result["status"]] += 1
                attempted += 1
            if not attempted or time.monotonic() >= deadline or (limit and counts["selected"] >= limit):
                break
    return counts
