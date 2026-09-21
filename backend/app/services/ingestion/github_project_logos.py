"""Conservative README logo discovery and bounded durable artwork ingestion.

Repository text is untrusted data. Never execute instructions, forward GitHub
credentials to image hosts, or mistake the first screenshot/badge for a logo.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import threading
import time
import warnings
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from PIL import Image

from backend.app.core.config import settings
from backend.app.core.github_artwork import GITHUB_DEFAULT_AVATAR_SHA256
from backend.app.services.ingestion.github_artwork_transport import ARTWORK_HOSTS, GitHubArtworkTransport
from backend.app.services.outbound_target_policy import normalize_http_url, pin_http_target, resolve_public_ips

MAX_DOWNLOAD = 4_000_000
MAX_STORED = 262144
_preferred_ips: dict[str, str] = {}
_image_decode_slots = threading.BoundedSemaphore(4)
_GITHUB_ASSET = re.compile(r"^/(?:user-attachments/assets|[A-Za-z0-9-]+/[A-Za-z0-9_.-]+/assets/[0-9]+)/[a-f0-9-]{36}$", re.I)
_ASSET_CDN = "github-production-user-asset-6210df.s3.amazonaws.com"
_REPO = re.compile(r"^[A-Za-z0-9-]+/[A-Za-z0-9_.-]+$")
_LOGO = re.compile(r"(?:^|[^a-z])(logo|logomark|wordmark|icon)(?:[^a-z]|$)", re.I)
_EXCLUDE = re.compile(r"badge|shield|sponsor|visitor|star-history|screenshot|open.?graph|thumbnail|processing|(?:^|[/_.-])og(?:[_.-]|$)|desktop.chat|diagram|architecture|workflow", re.I)
_SVG_TAGS = {"svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline",
             "polygon", "image", "pattern", "defs", "clipPath", "mask", "use", "text", "tspan", "filter",
             "feGaussianBlur", "feOffset", "feBlend", "feComposite", "feFlood",
             "feMerge", "feMergeNode", "feColorMatrix", "feDropShadow", "linearGradient", "radialGradient", "stop", "title", "desc"}
_SVG_ATTRS = {"viewBox", "width", "height", "x", "y", "x1", "x2", "y1", "y2", "cx",
              "cy", "r", "rx", "ry", "d", "points", "fill", "fill-rule", "fill-opacity",
              "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin", "stroke-opacity",
              "opacity", "transform", "id", "offset", "stop-color", "stop-opacity",
              "gradientUnits", "gradientTransform", "fx", "fy", "preserveAspectRatio",
              "clip-path", "clip-rule", "clipPathUnits", "mask", "maskUnits", "maskContentUnits",
              "font-family", "font-size", "font-weight", "font-style", "text-anchor", "letter-spacing",
              "dominant-baseline", "dx", "dy", "color", "stroke-miterlimit", "stroke-dasharray",
              "stroke-dashoffset", "vector-effect", "enable-background", "display", "visibility",
              "mask-type", "filter", "filterUnits", "primitiveUnits", "in", "in2", "result",
              "type", "values", "mode", "operator", "stdDeviation", "flood-color", "flood-opacity",
              "k1", "k2", "k3", "k4", "color-interpolation-filters", "patternUnits",
              "patternContentUnits", "patternTransform", "isolation", "white-space", "paint-order",
              "shape-rendering", "image-rendering", "text-rendering", "font-variant", "font-stretch",
              "line-height", "text-decoration", "word-spacing"}


def logo_url(raw: str, base: str) -> str:
    # GitHub renders /assets/logo.svg relative to the repository, not the CDN host.
    base_parts = urlsplit(base)
    if raw.startswith("/") and not raw.startswith("//") and base_parts.hostname == "raw.githubusercontent.com":
        segments = base_parts.path.strip("/").split("/")
        if len(segments) >= 4:
            raw = "/" + "/".join(segments[:3]) + raw
    url = normalize_http_url(urljoin(base, raw), allowed_ports={443})
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ARTWORK_HOSTS:
        raise ValueError("unsupported artwork host")
    if parts.hostname == "github.com":
        if re.fullmatch(r"/[A-Za-z0-9-]+\.png", parts.path) or _GITHUB_ASSET.fullmatch(parts.path):
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
    repo_name = urlsplit(download_url).path.split("/")[2] if len(urlsplit(download_url).path.split("/")) > 2 else ""
    def normalize_name(value):
        return re.sub(r"[^a-z0-9]", "", value.lower())
    for alt, source in candidates:
        try:
            evidence = f"{alt} {urlsplit(source).path}"
            brand_header = (normalize_name(alt) == normalize_name(repo_name)
                            and bool(repo_name) and 0 <= text.find(source) < 1500
                            and not re.search(r"(?:^|[^a-z])(hero|splash)(?:[^a-z]|$)", evidence, re.I))
            if (not _LOGO.search(evidence) and not brand_header) or _EXCLUDE.search(evidence):
                continue
            url = logo_url(source, download_url)
            # Logos of dependencies and sponsors are common in READMEs too.
            position = text.find(source)
            if not source or position < 0 or position > 6000:
                continue
            base_parts = urlsplit(download_url).path.strip("/").split("/")
            image_parts = urlsplit(url).path.strip("/").split("/")
            if urlsplit(url).hostname == "raw.githubusercontent.com" and image_parts[0].lower() != base_parts[0].lower():
                continue
            filename = image_parts[-1].rsplit(".", 1)[0]
            brand = normalize_name(repo_name)
            identity = normalize_name(alt + " " + filename)
            generic = re.fullmatch(r"(?:logo|icon|logomark|wordmark|app|project|brand|dark|light|white|black|color|full|text|horizontal|vertical|transparent|solid|with|background|main|core|outline|[\d_-])+", filename, re.I)
            if _LOGO.search(evidence) and not brand_header and brand not in identity and not generic:
                continue
        except ValueError:
            continue
        if url not in found:
            found.append(url)
    return tuple(found[:4])


def _svg_presentation_style(style: str) -> dict[str, str]:
    # Deliberately limited CSS: flatten presentation declarations into attributes.
    # No CSS is retained in the served SVG (imports, selectors, escapes, functions).
    result = {}
    for declaration in style.split(";"):
        if not declaration.strip():
            continue
        name, separator, value = declaration.partition(":")
        name, value = name.strip(), value.strip()
        if (not separator or name not in _SVG_ATTRS or name in {"id", "d", "points"}
                or not (re.fullmatch(r"[a-zA-Z0-9#.,% +\-]+", value)
                        or re.fullmatch(r"url\(#[\w-]+\)", value)
                        or re.fullmatch(r"rgba?\([0-9.,% ]+\)", value)
                        or (name == "font-family" and re.fullmatch(r"[a-zA-Z0-9 ,\-'\"]+", value)))):
            raise ValueError("unsupported SVG style")
        result[name] = value
    return result


def _flatten_svg_styles(root: ET.Element) -> None:
    rules = []
    for parent in root.iter():
        for node in list(parent):
            if node.tag.rsplit("}", 1)[-1] != "style":
                continue
            text = re.sub(r"/\*.*?\*/", "", node.text or "", flags=re.S)
            position = 0
            for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", text):
                if text[position:match.start()].strip():
                    raise ValueError("unsupported SVG stylesheet")
                selectors = [part.strip() for part in match[1].split(",")]
                if any(not re.fullmatch(r"[.#][a-zA-Z_][\w-]*", part) and part not in _SVG_TAGS for part in selectors):
                    raise ValueError("unsupported SVG selector")
                rules.append((selectors, _svg_presentation_style(match[2])))
                position = match.end()
            if text[position:].strip():
                raise ValueError("unsupported SVG stylesheet")
            parent.remove(node)
    for node in root.iter():
        classes = node.get("class", "").split()
        applicable = []
        for order, (selectors, attrs) in enumerate(rules):
            matching = [part for part in selectors if (part[0] == "." and part[1:] in classes)
                        or (part[0] == "#" and part[1:] == node.get("id"))
                        or part == node.tag.rsplit("}", 1)[-1]]
            if matching:
                applicable.append((max(100 if part[0] == "#" else 10 if part[0] == "." else 1 for part in matching), order, attrs))
        for _, _, attrs in sorted(applicable):
            node.attrib.update(attrs)
        if "style" in node.attrib:
            node.attrib.update(_svg_presentation_style(node.attrib.pop("style")))


def sanitize_image(body: bytes) -> tuple[bytes, str]:
    if not body or len(body) > MAX_DOWNLOAD:
        raise ValueError("invalid image size")
    if body.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = body.decode("utf-16")
        text = re.sub(r"encoding=['\"]UTF-16['\"]", 'encoding="UTF-8"', text, flags=re.I)
        body = text.encode("utf-8")
    elif body.startswith(b"\xef\xbb\xbf"):
        body = body[3:]
    if body.lstrip().startswith(b"<"):
        # Strip only the fixed public SVG DTD; no external resource is fetched.
        body = re.sub(br'<!DOCTYPE\s+svg\s+PUBLIC\s+[\']-//W3C//DTD SVG 1[.]1//EN[\']\s+[\']https?://www[.]w3[.]org/Graphics/SVG/1[.]1/DTD/svg11[.]dtd[\']\s*>', b'', body)
        body = re.sub(br'<!DOCTYPE\s+svg\s+PUBLIC\s+"-//W3C//DTD SVG 1[.]1//EN"\s+"https?://www[.]w3[.]org/Graphics/SVG/1[.]1/DTD/svg11[.]dtd"\s*>', b'', body)
        if len(body) > MAX_STORED or re.search(br"<!\s*(DOCTYPE|ENTITY)", body, re.I):
            raise ValueError("unsafe SVG declaration")
        root = ET.fromstring(body)
        if root.tag.rsplit("}", 1)[-1] != "svg":
            raise ValueError("not SVG")
        for parent in root.iter():
            for node in list(parent):
                if node.tag.rsplit("}", 1)[-1] in {"metadata", "namedview"} or node.tag == "{http://www.inkscape.org/namespaces/inkscape}path-effect":
                    parent.remove(node)
        _flatten_svg_styles(root)
        # Reject active/unknown nodes rather than serving partially altered artwork.
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1] not in _SVG_TAGS:
                raise ValueError("unsupported SVG element")
            for name, value in list(node.attrib.items()):
                if name in {"href", "{http://www.w3.org/1999/xlink}href"}:
                    if node.tag.rsplit("}", 1)[-1] == "image":
                        match = re.fullmatch(r"data:image/(?:png|jpeg|webp|gif);base64,([A-Za-z0-9+/=\s]+)", value)
                        if not match:
                            raise ValueError("external SVG image")
                        embedded = base64.b64decode(re.sub(r"\s", "", match[1]), validate=True)
                        image, mime = sanitize_image(embedded)
                        if mime != "image/webp":
                            raise ValueError("SVG images must be raster")
                        node.set(name, "data:image/webp;base64," + base64.b64encode(image).decode("ascii"))
                        continue
                    if not re.fullmatch(r"#[\w-]+", value):
                        raise ValueError("external SVG reference")
                    continue
                if name == "stdDeviation":
                    try:
                        deviations = [float(part) for part in value.replace(",", " ").split()]
                    except ValueError:
                        raise ValueError("invalid SVG blur") from None
                    if not 1 <= len(deviations) <= 2 or any(not 0 <= part <= 32 for part in deviations):
                        raise ValueError("SVG blur exceeds limit")
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
    with _image_decode_slots, warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(body)) as image:
            if image.width * image.height > 16_000_000:
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
    host = urlsplit(safe).hostname
    preferred = _preferred_ips.get(host)
    addresses = None
    if preferred and preferred != target.selected_ip:
        addresses = resolve_public_ips(host, reject_mixed=True)
        if preferred in addresses:
            target = pin_http_target(safe, resolver=lambda _: [preferred], allowed_ports={443})
    try:
        result = _download_pinned_logo(target, client)
        if hasattr(target, "selected_ip"):
            _preferred_ips[host] = target.selected_ip
        return result
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            raise
        error = exc
    # Some CDN edges are unreachable from the configured egress. Retry at most
    # two other IPv4 answers, after validating the ENTIRE DNS answer again.
    addresses = addresses or resolve_public_ips(host, reject_mixed=True)
    alternatives = [ip for ip in addresses if ":" not in ip and ip != target.selected_ip][:2]
    for ip in alternatives:
        alternate = pin_http_target(safe, resolver=lambda _, address=ip: [address], allowed_ports={443})
        try:
            result = _download_pinned_logo(alternate, client)
            _preferred_ips[host] = ip
            return result
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError) as exc:
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                raise
            error = exc
    raise error


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
        if (target.headers.get("Host") == "github.com"
                and _GITHUB_ASSET.fullmatch(urlsplit(target.request_url).path)
                and response.status_code in {301, 302, 303, 307, 308}):
            location = logo_url(response.headers.get("location", ""), "")
            if urlsplit(location).hostname != _ASSET_CDN:
                raise ValueError("unsupported GitHub asset redirect")
            return download_logo(location, client)
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


def resolve_owner_avatars(owners: list[str], client: httpx.Client) -> dict[str, str]:
    """Resolve up to 100 official CDN identities in one authenticated API request.

    The token stays on api.github.com; returned URLs are untrusted image input.
    Partial GraphQL failures preserve other owners and fall back to .png normally.
    """
    from backend.app.services.ingestion.source_github import _build_headers, _get_token

    owners = list(dict.fromkeys(owner for owner in owners if re.fullmatch(r"[A-Za-z0-9-]+", owner)))[:100]
    if not owners or not _get_token():
        return {}
    fields = " ".join(f"o{i}: repositoryOwner(login: {json.dumps(owner)}) {{ avatarUrl(size: 128) }}"
                      for i, owner in enumerate(owners))
    try:
        response = client.post("https://api.github.com/graphql", headers=_build_headers(),
                               json={"query": "query { " + fields + " }"})
        response.raise_for_status()
        data = response.json().get("data") or {}
        result = {}
        for i, owner in enumerate(owners):
            raw = (data.get(f"o{i}") or {}).get("avatarUrl", "")
            if not isinstance(raw, str):
                continue
            try:
                safe = logo_url(raw, raw)
                parts = urlsplit(safe)
                if parts.hostname == "avatars.githubusercontent.com" and re.fullmatch(r"/u/[0-9]+", parts.path):
                    result[owner] = safe
            except ValueError:
                continue
        return result
    except (httpx.HTTPError, ValueError, AttributeError, TypeError):
        return {}


def resolve_moved_repository_artwork(names: list[str], client: httpx.Client) -> dict[str, tuple[str, str]]:
    """GitHub resolves repository moves even after the original owner disappears."""
    from backend.app.services.ingestion.source_github import _build_headers, _get_token

    names = list(dict.fromkeys(name for name in names if _REPO.fullmatch(name)))[:100]
    if not names or not _get_token():
        return {}
    fields = []
    for i, name in enumerate(names):
        owner, repo = name.split("/")
        fields.append(f"r{i}: repository(owner: {json.dumps(owner)}, name: {json.dumps(repo)}) "
                      "{ nameWithOwner owner { avatarUrl(size: 128) } }")
    try:
        response = client.post("https://api.github.com/graphql", headers=_build_headers(),
                               json={"query": "query { " + " ".join(fields) + " }"})
        response.raise_for_status()
        data = response.json().get("data") or {}
        result = {}
        for i, name in enumerate(names):
            row = data.get(f"r{i}") or {}
            canonical = row.get("nameWithOwner", "")
            raw = (row.get("owner") or {}).get("avatarUrl", "")
            if not isinstance(canonical, str) or not _REPO.fullmatch(canonical) or not isinstance(raw, str):
                continue
            try:
                safe = logo_url(raw, raw)
                parts = urlsplit(safe)
                if parts.hostname == "avatars.githubusercontent.com" and re.fullmatch(r"/u/[0-9]+", parts.path):
                    result[name] = (canonical, safe)
            except ValueError:
                continue
        return result
    except (httpx.HTTPError, ValueError, AttributeError, TypeError):
        return {}


def collect_logo(
    full_name: str, api_client: httpx.Client, image_client: httpx.Client, readme_enabled: bool = True,
    owner_avatar_url: str = "",
) -> dict[str, Any]:
    from backend.app.services.ingestion.source_github import fetch_github_readme_snapshot

    if not _REPO.fullmatch(full_name):
        return {"status": "failed"}
    snapshot = fetch_github_readme_snapshot(full_name, api_client) if readme_enabled else None
    rate_limited = snapshot is not None and snapshot.status == "rate_limited"
    candidates = snapshot.logo_candidates if snapshot and snapshot.status == "succeeded" else ()
    # Cache the owner avatar too: browsers must not depend on GitHub connectivity.
    avatar = owner_avatar_url or f"https://github.com/{full_name.split('/')[0]}.png?size=128"
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
    avatars: dict[str, str] = {}
    moved: dict[str, tuple[str, str]] = {}
    with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as api, httpx.Client(
        timeout=15, follow_redirects=False, trust_env=False,
        transport=GitHubArtworkTransport(proxy=settings.github_artwork_proxy or settings.outbound_proxy or None),
    ) as images, ThreadPoolExecutor(max_workers=max(1, min(workers, 32))) as pool:
        def collect(row):
            if time.monotonic() >= deadline:
                return None
            name, avatar = moved.get(row["full_name"], (
                row["full_name"], avatars.get(row["full_name"].split("/")[0], ""),
            ))
            result = collect_logo(name, api, images, not readme_limited.is_set(), avatar)
            if result.get("readme_rate_limited"):
                readme_limited.set()
            time.sleep(max(0.0, interval))
            return row, result

        while True:
            remaining = max(0, limit - counts["selected"]) if limit else 1000
            rows = repository.pending(min(remaining, 1000))
            if not rows:
                break
            owners = list(dict.fromkeys(row["full_name"].split("/")[0] for row in rows))
            missing = [owner for owner in owners if owner not in avatars]
            for offset in range(0, len(missing), 100):
                avatars.update(resolve_owner_avatars(missing[offset:offset + 100], api))
            unresolved = [row["full_name"] for row in rows
                          if row["full_name"].split("/")[0] not in avatars and row["full_name"] not in moved]
            for offset in range(0, len(unresolved), 100):
                moved.update(resolve_moved_repository_artwork(unresolved[offset:offset + 100], api))
            attempted = 0
            for future in as_completed([pool.submit(collect, row) for row in rows]):
                item = future.result()
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
