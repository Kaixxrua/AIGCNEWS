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
import subprocess
import sys
import time
import warnings
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from curl_cffi import CurlECode, CurlOpt, ffi, lib
from curl_cffi.curl import CURL_WRITEFUNC_ERROR, CurlError
from curl_cffi.requests import AsyncSession
from PIL import Image, ImageOps

from backend.app.core.config import settings
from backend.app.services.outbound_target_policy import pin_http_target
from backend.app.services.project_catalog.game_poster_search import SEARCH_ENGINES, bounded_engines

PAGE_BYTES = 1024 * 1024
IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_PIXELS = 16_000_000
IMAGE_RESOURCE_SECONDS = 30
IMAGE_REQUEST_SECONDS = 18
_TRANSIENT_IMAGE_ERRORS = frozenset({CurlECode.COULDNT_CONNECT, CurlECode.OPERATION_TIMEDOUT,
                                    CurlECode.GOT_NOTHING, CurlECode.SEND_ERROR, CurlECode.RECV_ERROR})
SEARCH_WORKER_SECONDS = 22
ASSET_BASE = "https://aigcnews.cn/api/media/site/game-posters/"
_UNSAFE = re.compile(r"[\x00-\x20\x7f-\x9f\\]")
_UNSAFE_DECODED_PATH = re.compile(r"[\x00-\x1f\x7f-\x9f\\]")
_CACHED_POSTER = re.compile(re.escape(ASSET_BASE) + r"([0-9a-f]{64}\.jpg)\Z")


class PosterResourceError(RuntimeError):
    """Only a stable non-secret code may be shown in a tool transcript."""

    def __init__(self, code: str, *, attempts: list[dict] | None = None):
        super().__init__(code)
        self.attempts = attempts or []


def _search_attempts(value: Any) -> list[dict]:
    """Keep diagnostic codes, never provider messages, response HTML or URLs."""
    if not isinstance(value, list):
        return []
    output = []
    for row in value[:2]:
        if (not isinstance(row, dict) or not isinstance(row.get("engine"), str) or row["engine"] not in SEARCH_ENGINES
                or not isinstance(row.get("status"), str) or row["status"] not in {"succeeded", "empty", "unavailable"}):
            continue
        public = {"engine": row["engine"], "status": row["status"]}
        for key, low, high in (("elapsedMs", 0, 22000), ("resultCount", 0, 6), ("httpStatus", 100, 599)):
            number = row.get(key)
            if type(number) is int and low <= number <= high:
                public[key] = number
        if type(row.get("retryCount")) is int and row["retryCount"] in (0, 1):
            public["retryCount"] = row["retryCount"]
        if row.get("parser") == "yahoo_headings":
            public["parser"] = "yahoo_headings"
        if isinstance(row.get("reason"), str) and row["reason"] in {"provider_http", "provider_response_oversize", "worker_deadline", "provider_challenge"}:
            public["reason"] = row["reason"]
        if isinstance(row.get("errorType"), str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", row["errorType"]):
            public["errorType"] = row["errorType"]
        output.append(public)
    return output


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


async def _search_worker(payload: bytes, environment: dict[str, str]) -> bytes:
    """Own a bounded worker without server-loop child watchers or reader threads.

    Search subprocess operations failed after repeated requests in the running
    server. Nonblocking pipes keep I/O cancellable and bounded while Popen owns
    waitpid independently of the event loop and its default thread pool.
    """
    if len(payload) > 8192:
        raise PosterResourceError("search_input_too_large")
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("game_poster_search.py"))],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        env=environment,
    )
    try:
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        output = bytearray()
        sent, eof = 0, False
        deadline = asyncio.get_running_loop().time() + SEARCH_WORKER_SECONDS
        while True:
            if not process.stdin.closed:
                try:
                    sent += os.write(process.stdin.fileno(), payload[sent:])
                except BlockingIOError:
                    pass
                if sent == len(payload):
                    process.stdin.close()
            try:
                chunk = os.read(process.stdout.fileno(), 8192)
            except BlockingIOError:
                chunk = None
            if chunk:
                output.extend(chunk)
                if len(output) > 32768:
                    raise PosterResourceError("search_output_too_large")
            elif chunk == b"":
                eof = True
            if process.poll() is not None and eof:
                if process.returncode != 0:
                    raise PosterResourceError("search_unavailable")
                return bytes(output)
            if asyncio.get_running_loop().time() >= deadline:
                raise PosterResourceError("search_timeout")
            await asyncio.sleep(0.025)
    finally:
        if process.poll() is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        # Reap even during cancellation; this waits only for a killed child,
        # never its network work. Avoid the loop's failed process watcher.
        process.wait(timeout=2)
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                stream.close()


async def search_public_web(query: str, *, engines: tuple[str, ...] = ("google", "yahoo")) -> dict:
    """Run real public search in an isolated, killable, minimal-env process."""
    if not isinstance(query, str) or not 3 <= len(query) <= 300 or re.search(r"[\x00-\x1f\x7f]", query):
        raise PosterResourceError("invalid_query")
    try:
        engines = bounded_engines(engines)
    except ValueError as exc:
        raise PosterResourceError("invalid_search_engines") from exc
    environment = {key: os.environ[key] for key in ("PATH", "LANG", "SSL_CERT_FILE", "SSL_CERT_DIR") if key in os.environ}
    try:
        payload = json.dumps({"query": query, "proxy": settings.outbound_proxy or None, "engines": engines}).encode()
        output = await _search_worker(payload, environment)
        data = json.loads(output)
        attempts = _search_attempts(data.get("attempts")) if isinstance(data, dict) else []
        if not isinstance(data, dict) or data.get("unavailable") or not isinstance(data.get("results"), list):
            raise PosterResourceError("search_unavailable", attempts=attempts)
        rows = []
        for row in data["results"][:6]:
            if not isinstance(row, dict):
                continue
            if "imageUrl" in row:
                try:
                    source, image_url = safe_web_url(row.get("url")), safe_web_url(row["imageUrl"])
                except PosterResourceError:
                    continue
                # The subprocess cannot turn an arbitrary URL or extra field
                # into trusted evidence. Network fetches still pin both hosts.
                row = {"url": source, "imageUrl": image_url,
                       "title": row["title"][:300] if isinstance(row.get("title"), str) else "",
                       "snippet": row["snippet"][:600] if isinstance(row.get("snippet"), str) else ""}
            rows.append(row)
        return {"engine": str(data.get("engine") or "ddgs")[:30], "results": rows,
                "workerTransport": "direct_child", "attempts": attempts}
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired) as exc:
        raise PosterResourceError("search_unavailable") from exc


async def search_public_artwork(query: str) -> dict:
    """Keep precise game-database queries, otherwise discover images and sources."""
    # Preserve the existing query validator, including its non-string cases.
    game_database = isinstance(query, str) and re.search(r"(?<!\S)site:gamesdb\.launchbox-app\.com(?=\s|$)", query, re.I)
    engines = ("google", "yahoo") if game_database else ("bing_images", "yahoo")
    return await search_public_web(query, engines=engines)


async def fetch_poster_resource(url: str, *, image: bool = False) -> PosterResource:
    """Same proxy-safe CONNECT_TO pin as hotword_web; revalidate every hop."""
    limit = IMAGE_BYTES if image else PAGE_BYTES
    deadline = asyncio.get_running_loop().time() + (IMAGE_RESOURCE_SECONDS if image else 15)
    redirects = 0
    retried = False
    try:
        async with asyncio.timeout_at(deadline):
            while redirects < 4:
                url = safe_web_url(url)
                target = await asyncio.to_thread(pin_http_target, url, allowed_ports={443}, reject_mixed=True)
                # The await above is also a cancellation boundary before any I/O.
                parts = urlsplit(target.logical_url)
                ip = f"[{target.selected_ip}]" if ":" in target.selected_ip else target.selected_ip
                connections = lib.curl_slist_append(ffi.NULL, f"{parts.hostname}:443:{ip}:443".encode())
                if connections == ffi.NULL:
                    raise PosterResourceError("network_unavailable")
                body = bytearray()
                oversized = False

                def receive(chunk: bytes) -> int:
                    nonlocal oversized
                    if len(body) + len(chunk) > limit:
                        oversized = True
                        return CURL_WRITEFUNC_ERROR
                    body.extend(chunk)
                    return len(chunk)

                try:
                    async with AsyncSession(
                        proxy=settings.outbound_proxy or None, verify=True, trust_env=True,
                        headers={"User-Agent": "Mozilla/5.0 AIGCNEWS-PortShelf/1.0",
                                 "Accept": "image/jpeg,image/png,image/webp,image/gif" if image else "text/html,application/xhtml+xml"},
                        curl_options={CurlOpt.CONNECT_TO: connections, CurlOpt.HTTPPROXYTUNNEL: 1,
                                      CurlOpt.MAXFILESIZE_LARGE: limit},
                    ) as client:
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            raise TimeoutError
                        response = await client.get(target.logical_url, allow_redirects=False,
                                                    timeout=min(IMAGE_REQUEST_SECONDS if image else 12, remaining), content_callback=receive)
                except Exception as exc:
                    # libcurl can reject Content-Length before streaming, or
                    # the callback can stop an unknown/chunked response. Both
                    # are size failures, without exposing transport messages.
                    if oversized or getattr(exc, "code", None) == CurlECode.FILESIZE_EXCEEDED:
                        raise PosterResourceError("image_too_large" if image else "page_too_large") from None
                    status = getattr(getattr(exc, "response", None), "status_code", 0)
                    if (image and not retried and isinstance(exc, CurlError) and exc.code in _TRANSIENT_IMAGE_ERRORS
                            and status in {0, 200}):
                        # A fresh connection and DNS pin are required, even for
                        # the same URL. One shared retry never resets redirects
                        # or the resource deadline, and never repeats vision.
                        retried = True
                        continue
                    raise
                finally:
                    lib.curl_slist_free_all(connections)
                if oversized:
                    raise PosterResourceError("image_too_large" if image else "page_too_large")
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise PosterResourceError("invalid_redirect")
                    url = urljoin(target.logical_url, location)
                    redirects += 1
                    continue
                content_type = response.headers.get("content-type", "").lower().split(";", 1)[0].strip()
                permitted = {"image/jpeg", "image/png", "image/webp", "image/gif"} if image else {"text/html", "application/xhtml+xml"}
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
    if len(payload) > IMAGE_BYTES:
        raise PosterResourceError("image_too_large")
    if not payload:
        raise PosterResourceError("invalid_image")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(payload)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP", "GIF"} or min(source.size) < 160 or source.width * source.height > IMAGE_PIXELS:
                    raise PosterResourceError("invalid_image")
                if source.format == "GIF":
                    # A poster needs one bounded raster, not animation. Never
                    # inspect n_frames or seek later frames, which can trigger
                    # unbounded animation work despite a small file size.
                    source.seek(0)
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
