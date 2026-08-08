"""微信公众号图片代理：把 mmbiz CDN 图片经服务端转发给浏览器。

背景：文章正文图片托管在 mmbiz.qpic.cn，服务端回源必须携带
`Referer: https://mp.weixin.qq.com/`（防盗链），浏览器直连时
referrerpolicy 行为不稳定，故以同源代理统一出口，模式与
routes_x_media.py 一致。

GET /api/media/wechat/proxy?url=<https-url>
  校验白名单后回源，图片按 URL 哈希落盘缓存（mmbiz 图 URL 内容寻址、
  永久不变），命中直读本地文件；上游 404/非图片记 5 分钟负缓存，
  避免每次渲染重复回源。

约束：
  - 仅放行 mmbiz 主机白名单，防 SSRF 开放代理
  - 仅接受 200 + image/* + 15MB 上限；3xx 不跟随（统一 502）
  - 公开访问（与 /api/media/papers 一致：<img> 标签无法携带
    Authorization 头）
  - 直连回源：mmbiz 是国内 CDN，海外代理出口反而更易触发风控
    （与 wechat_sogou transport 的直连策略一致）
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import FileResponse

from backend.app.core.client_ip import client_ip_from_request
from backend.app.core.config import settings
from backend.app.services.auth.rate_limit import (
    RateLimitExceededError,
    hit_rate_limit,
)
from backend.app.services.media_cache import enforce_cache_budget, prune_expired_entries

router = APIRouter()
logger = logging.getLogger(__name__)

ALLOWED_MEDIA_HOSTS = frozenset(
    {
        "mmbiz.qpic.cn",
        "mmbiz.qlogo.cn",
    }
)

_UPSTREAM_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
_UPSTREAM_REFERER = "https://mp.weixin.qq.com/"

_CACHE_CONTROL = "public, max-age=86400"
_MAX_IMAGE_BYTES = 15 * 1024 * 1024
_NEGATIVE_TTL_SECONDS = 300.0

# wx_fmt 值仅用于推断文件后缀，严格白名单，绝不反射进路径
_FORMAT_EXTENSIONS = {
    "jpeg": ".jpg",
    "jpg": ".jpg",
    "png": ".png",
    "gif": ".gif",
    "webp": ".webp",
    "bmp": ".bmp",
}
_CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
}

_image_locks: dict[str, asyncio.Lock] = {}
_negative_cache: dict[str, float] = {}  # url -> 负缓存过期时刻（time.monotonic）

# 匿名 IP 级回源限速：每次缓存 miss 代价是一次上游回源 + 磁盘写入。
# 30 次/10 分钟对齐 routes_x_media 封面的匿名端点口径；磁盘缓存/负缓存
# 命中不计费，正常浏览重复渲染不消耗配额。
_MEDIA_FETCH_RATE_LIMIT = 30
_MEDIA_RATE_LIMIT_WINDOW_SECONDS = 600


async def _enforce_media_fetch_rate_limit(request: Request) -> None:
    """回源路径的匿名 IP 级限速；Redis 不可用时放行（与既有端点同口径）。"""
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return
    try:
        await hit_rate_limit(
            redis_client,
            action="wechat_media_fetch",
            identity=client_ip_from_request(request),
            limit=_MEDIA_FETCH_RATE_LIMIT,
            window_seconds=_MEDIA_RATE_LIMIT_WINDOW_SECONDS,
        )
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail="media fetch rate limited, retry later",
            headers={"Retry-After": str(_MEDIA_RATE_LIMIT_WINDOW_SECONDS)},
        ) from exc
    except Exception:
        logger.warning(
            "[WeChatMediaProxy] rate limit check failed, allowing request",
            exc_info=True,
        )


def validate_wechat_media_url(raw_url: str) -> str:
    """校验并返回可代理的图片 URL；任何偏离白名单的输入直接 4xx。"""
    try:
        parsed = urlsplit(raw_url)
        port = parsed.port  # 非法端口在访问属性时抛 ValueError
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="media url malformed") from exc
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="media url must be https")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="media url must not carry userinfo")
    if (parsed.hostname or "") not in ALLOWED_MEDIA_HOSTS:
        raise HTTPException(status_code=403, detail="media host not allowed")
    if port not in (None, 443):
        raise HTTPException(status_code=400, detail="media url port not allowed")
    return raw_url


_shared_client: httpx.AsyncClient | None = None


def _get_upstream_client() -> httpx.AsyncClient:
    """进程级共享直连客户端（测试缝：monkeypatch 注入 MockTransport）。"""
    global _shared_client
    if _shared_client is None:
        _shared_client = httpx.AsyncClient(
            proxy=None,
            trust_env=False,
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=15.0, pool=10.0),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        )
    return _shared_client


def _cache_dir() -> Path:
    """图片缓存目录（测试缝：monkeypatch 到 tmp_path）。"""
    path = Path(settings.wechat_media_cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_path(url: str, content_type: str | None = None) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    extension = ""
    fmt = parse_qs(urlsplit(url).query).get("wx_fmt", [""])[0].lower()
    extension = _FORMAT_EXTENSIONS.get(fmt, "")
    if not extension and content_type:
        extension = _CONTENT_TYPE_EXTENSIONS.get(content_type.split(";")[0].strip().lower(), "")
    return _cache_dir() / f"{digest}{extension or '.img'}"


def _existing_cache_path(url: str) -> Path | None:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    for candidate in _cache_dir().glob(f"{digest}.*"):
        return candidate
    return None


def _cached_file_response(path: Path) -> FileResponse:
    return FileResponse(path, headers={"Cache-Control": _CACHE_CONTROL})


def _mark_negative(url: str) -> None:
    _negative_cache[url] = time.monotonic() + _NEGATIVE_TTL_SECONDS
    prune_expired_entries(_negative_cache)


async def _fetch_image(url: str) -> tuple[bytes, str]:
    """回源取图；成功返回 (内容, Content-Type)，失败抛 HTTPException。"""
    client = _get_upstream_client()
    headers = {
        "User-Agent": _UPSTREAM_USER_AGENT,
        "Referer": _UPSTREAM_REFERER,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
    }
    try:
        request = client.build_request("GET", url, headers=headers)
        response = await client.send(request)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="media upstream timeout") from exc
    except httpx.HTTPError as exc:
        logger.warning("[WeChatMediaProxy] upstream connect failed: %s", exc)
        raise HTTPException(status_code=502, detail="media upstream unreachable") from exc
    try:
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="media upstream not found")
        if 300 <= response.status_code < 400:
            logger.warning(
                "[WeChatMediaProxy] unexpected redirect %s for %s",
                response.status_code,
                url,
            )
            raise HTTPException(status_code=502, detail="media upstream redirect rejected")
        if response.status_code != 200:
            logger.warning(
                "[WeChatMediaProxy] unexpected upstream status %s for %s",
                response.status_code,
                url,
            )
            raise HTTPException(status_code=502, detail="media upstream error")
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            logger.warning(
                "[WeChatMediaProxy] non-image content-type %r for %s",
                content_type,
                url,
            )
            raise HTTPException(status_code=502, detail="media upstream not an image")
        body = response.content
        if len(body) > _MAX_IMAGE_BYTES:
            raise HTTPException(status_code=502, detail="media upstream image too large")
        return body, content_type
    finally:
        await response.aclose()


@router.get("/media/wechat/proxy")
async def proxy_wechat_media(request: Request, url: str = Query(..., min_length=1)):
    target = validate_wechat_media_url(url)

    cached = _existing_cache_path(target)
    if cached is not None:
        return _cached_file_response(cached)

    if _negative_cache.get(target, 0.0) > time.monotonic():
        raise HTTPException(status_code=404, detail="media unavailable")

    lock = _image_locks.setdefault(target, asyncio.Lock())
    async with lock:
        try:
            # 双检：等待锁期间并发请求可能已落盘
            cached = _existing_cache_path(target)
            if cached is not None:
                return _cached_file_response(cached)
            # 仅真实回源才计费；缓存/负缓存命中不消耗配额
            await _enforce_media_fetch_rate_limit(request)
            try:
                body, content_type = await _fetch_image(target)
            except HTTPException as exc:
                # 上游 404 / 非图片是稳定态，记负缓存；超时/连接错误是瞬态不记
                if exc.status_code in (404,) or exc.detail == "media upstream not an image":
                    _mark_negative(target)
                raise
            cache_path = _cache_path(target, content_type)
            tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
            tmp_path.write_bytes(body)
            tmp_path.replace(cache_path)  # 原子落盘，避免并发读到半成品
            await enforce_cache_budget(
                _cache_dir(),
                max_bytes=settings.media_cache_max_bytes,
                max_age_seconds=settings.media_cache_max_age_seconds,
            )
            return _cached_file_response(cache_path)
        finally:
            _image_locks.pop(target, None)
