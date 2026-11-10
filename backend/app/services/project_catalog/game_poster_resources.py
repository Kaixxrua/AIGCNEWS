"""Bounded public-page/image transport and content-addressed public JPEG cache."""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import re
import secrets
import stat
import sys
import time
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from curl_cffi import CurlOpt, ffi, lib
from curl_cffi.curl import CURL_WRITEFUNC_ERROR
from curl_cffi.requests import AsyncSession
from PIL import Image, ImageOps

from backend.app.core.config import settings
from backend.app.services.outbound_target_policy import pin_http_target
from backend.app.services.project_catalog.game_poster_search import bounded_engines

PAGE_BYTES = 1024 * 1024
IMAGE_BYTES = 4 * 1024 * 1024
IMAGE_PIXELS = 16_000_000
ASSET_BASE = "https://aigcnews.cn/api/media/site/game-posters/"
_UNSAFE = re.compile(r"[\x00-\x20\x7f-\x9f\\]")
_UNSAFE_DECODED_PATH = re.compile(r"[\x00-\x1f\x7f-\x9f\\]")
_CACHED_POSTER = re.compile(re.escape(ASSET_BASE) + r"([0-9a-f]{64}\.jpg)\Z")


class PosterResourceError(RuntimeError):
    """Only a stable non-secret code may be shown in a tool transcript."""


def safe_web_url(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048 or _UNSAFE.search(value) or any(char.isspace() for char in value):
        raise PosterResourceError("unsafe_url")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or parsed.username is not None or parsed.password is not None or parsed.port is not None:
            raise ValueError
        if not re.fullmatch(r"[a-z0-9.-]+", host) or "." not in host or host.endswith((".localhost", ".local", ".internal", ".lan", ".")) or re.fullmatch(r"[0-9.]+", host):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise PosterResourceError("unsafe_url")
        path = unquote(parsed.path)
        if _UNSAFE_DECODED_PATH.search(path) or "%" in path or "//" in path or any(part in {".", ".."} for part in path.split("/")):
            raise ValueError
        return urlunsplit(("https", host.lower(), parsed.path or "/", parsed.query, ""))
    except (ValueError, UnicodeError) as exc:
        raise PosterResourceError("unsafe_url") from exc


@dataclass(frozen=True)
class PosterResource:
    url: str
    body: bytes
    content_type: str


async def search_public_web(query: str, *, engines: tuple[str, ...] = ("yahoo", "duckduckgo")) -> dict:
    """A subprocess can be killed; cancelling a to_thread(DDGS) cannot stop I/O."""
    if not isinstance(query, str) or not 3 <= len(query) <= 300 or re.search(r"[\x00-\x1f\x7f]", query):
        raise PosterResourceError("invalid_query")
    try:
        engines = bounded_engines(engines)
    except ValueError as exc:
        raise PosterResourceError("invalid_search_engines") from exc
    environment = {key: os.environ[key] for key in ("PATH", "LANG", "SSL_CERT_FILE", "SSL_CERT_DIR") if key in os.environ}
    process = await asyncio.create_subprocess_exec(
        sys.executable, str(Path(__file__).with_name("game_poster_search.py")),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, env=environment,
    )
    try:
        payload = json.dumps({"query": query, "proxy": settings.outbound_proxy or None, "engines": engines}).encode()
        output, _ = await asyncio.wait_for(process.communicate(payload), timeout=22)
        if process.returncode != 0 or len(output) > 32768:
            raise PosterResourceError("search_unavailable")
        data = json.loads(output)
        if not isinstance(data, dict) or data.get("unavailable") or not isinstance(data.get("results"), list):
            raise PosterResourceError("search_unavailable")
        return {"engine": str(data.get("engine") or "ddgs")[:30], "results": data["results"][:6]}
    except (ValueError, TimeoutError) as exc:
        raise PosterResourceError("search_unavailable") from exc
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()


async def fetch_poster_resource(url: str, *, image: bool = False) -> PosterResource:
    """Same proxy-safe CONNECT_TO pin as hotword_web; revalidate every hop."""
    limit = IMAGE_BYTES if image else PAGE_BYTES
    try:
        async with asyncio.timeout(15):
            for _ in range(4):
                url = safe_web_url(url)
                target = await asyncio.to_thread(pin_http_target, url, allowed_ports={443}, reject_mixed=True)
                # The await above is also a cancellation boundary before any I/O.
                parts = urlsplit(target.logical_url)
                ip = f"[{target.selected_ip}]" if ":" in target.selected_ip else target.selected_ip
                connections = lib.curl_slist_append(ffi.NULL, f"{parts.hostname}:443:{ip}:443".encode())
                if connections == ffi.NULL:
                    raise PosterResourceError("network_unavailable")
                body = bytearray()

                def receive(chunk: bytes) -> int:
                    if len(body) + len(chunk) > limit:
                        return CURL_WRITEFUNC_ERROR
                    body.extend(chunk)
                    return len(chunk)

                try:
                    async with AsyncSession(
                        proxy=settings.outbound_proxy or None, verify=True, trust_env=True,
                        headers={"User-Agent": "Mozilla/5.0 AIGCNEWS-PortShelf/1.0",
                                 "Accept": "image/jpeg,image/png,image/webp" if image else "text/html,application/xhtml+xml"},
                        curl_options={CurlOpt.CONNECT_TO: connections, CurlOpt.HTTPPROXYTUNNEL: 1,
                                      CurlOpt.MAXFILESIZE_LARGE: limit},
                    ) as client:
                        response = await client.get(target.logical_url, allow_redirects=False, timeout=12, content_callback=receive)
                finally:
                    lib.curl_slist_free_all(connections)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise PosterResourceError("invalid_redirect")
                    url = urljoin(target.logical_url, location)
                    continue
                content_type = response.headers.get("content-type", "").lower().split(";", 1)[0].strip()
                permitted = {"image/jpeg", "image/png", "image/webp"} if image else {"text/html", "application/xhtml+xml"}
                if response.status_code != 200 or content_type not in permitted:
                    raise PosterResourceError("invalid_image" if image else "page_unavailable")
                return PosterResource(target.logical_url, bytes(body), content_type)
    except asyncio.CancelledError:
        raise
    except PosterResourceError:
        raise
    except Exception as exc:
        raise PosterResourceError("network_unavailable") from exc
    raise PosterResourceError("too_many_redirects")


def clean_poster_jpeg(payload: bytes) -> tuple[bytes, int, int]:
    if not payload or len(payload) > IMAGE_BYTES:
        raise PosterResourceError("invalid_image")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(payload)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"} or min(source.size) < 160 or source.width * source.height > IMAGE_PIXELS:
                    raise PosterResourceError("invalid_image")
                source.load()
                oriented = ImageOps.exif_transpose(source).convert("RGB")
                oriented.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
                clean = Image.new("RGB", oriented.size)
                clean.paste(oriented)
                output = BytesIO()
                clean.save(output, format="JPEG", quality=88)
                return output.getvalue(), clean.width, clean.height
    except PosterResourceError:
        raise
    except Exception as exc:
        raise PosterResourceError("invalid_image") from exc


def poster_cache_dir() -> Path:
    root = Path(settings.site_assets_storage_dir).absolute()
    # Configuration paths are trusted but symlinks must never redirect cache
    # writes or pruning outside the site's dedicated public subdirectory.
    if ".." in root.parts:
        raise PosterResourceError("unsafe_cache")
    for path in (root, *root.parents):
        if path.is_symlink():
            raise PosterResourceError("unsafe_cache")
    root.mkdir(parents=True, exist_ok=True)
    directory = root / "game-posters"
    if directory.is_symlink():
        raise PosterResourceError("unsafe_cache")
    directory.mkdir(exist_ok=True)
    if any(child.is_symlink() for child in directory.iterdir()):
        raise PosterResourceError("unsafe_cache")
    return directory


def is_cached_poster_url(url: str) -> bool:
    return bool(isinstance(url, str) and _CACHED_POSTER.fullmatch(url))


def cached_poster_exists(url: str) -> bool:
    """Read-only local check; expired assets can be repaired by a later POST."""
    match = _CACHED_POSTER.fullmatch(url) if isinstance(url, str) else None
    if not match:
        return False
    directory = Path(settings.site_assets_storage_dir).absolute() / "game-posters"
    try:
        if ".." in directory.parts or any(path.is_symlink() for path in (directory, *directory.parents)):
            return False
        descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            entry = os.stat(match[1], dir_fd=descriptor, follow_symlinks=False)
            return stat.S_ISREG(entry.st_mode) and entry.st_size > 0
        finally:
            os.close(descriptor)
    except OSError:
        return False


def _store_jpeg(directory: Path, payload: bytes) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    filename = digest + ".jpg"
    temporary = "." + secrets.token_hex(16) + ".tmp"
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            existing = os.stat(filename, dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISREG(existing.st_mode):
                raise PosterResourceError("unsafe_cache")
        except FileNotFoundError:
            pass
        file = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o644, dir_fd=descriptor)
        with os.fdopen(file, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, filename, src_dir_fd=descriptor, dst_dir_fd=descriptor)
        return ASSET_BASE + filename
    finally:
        try:
            os.unlink(temporary, dir_fd=descriptor)
        except FileNotFoundError:
            pass
        os.close(descriptor)


def _prune_posters(directory: Path, max_bytes: int, max_age: float) -> None:
    """Strict per-write budget; do not inherit the shared cache's 10m grace."""
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        entries = []
        now = time.time()
        for name in os.listdir(descriptor):
            try:
                entry = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(entry.st_mode):
                raise PosterResourceError("unsafe_cache")
            if not stat.S_ISREG(entry.st_mode):
                continue
            if now - entry.st_mtime > max_age:
                try:
                    os.unlink(name, dir_fd=descriptor)
                except FileNotFoundError:
                    pass
            else:
                entries.append((entry.st_mtime, entry.st_size, name))
        total = sum(size for _, size, _ in entries)
        for _, size, name in sorted(entries):
            if total <= max_bytes:
                break
            try:
                os.unlink(name, dir_fd=descriptor)
            except FileNotFoundError:
                pass  # A concurrent writer may have pruned the same old file.
            total -= size
    finally:
        os.close(descriptor)


async def cache_poster(payload: bytes) -> dict:
    jpeg, width, height = await asyncio.to_thread(clean_poster_jpeg, payload)
    directory = await asyncio.to_thread(poster_cache_dir)
    url = await asyncio.to_thread(_store_jpeg, directory, jpeg)
    await asyncio.to_thread(_prune_posters, directory, min(settings.media_cache_max_bytes, 128 * 1024 * 1024),
                            min(settings.media_cache_max_age_seconds, 7 * 86400))
    if not await asyncio.to_thread(cached_poster_exists, url):
        raise PosterResourceError("cache_unavailable")
    return {"url": url, "sha256": hashlib.sha256(jpeg).hexdigest(), "width": width, "height": height}
