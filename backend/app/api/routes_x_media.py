"""X/Twitter 媒体流式代理与视频封面：把 twimg CDN 资源经服务端转发给浏览器。

背景：X 媒体直链（pbs.twimg.com / video.twimg.com）在部分网络不可达
（video.twimg.com 常被单独封锁，图片可加载但视频无法播放）；服务端
出站走 WireGuard 网关 socks 代理可正常回源，故以同源流式代理兜底。

GET /api/media/x/proxy?url=<https-url>
  流式转发原图/原视频：透传 Range（视频 seek 依赖 206），上游状态码
  原样回传；3xx 不跟随（跟随会放开白名单约束，统一按 502）。

GET /api/media/x/img/<host>/<path>?<query>
  查询形态的路径式变体（同一校验与转发），供边缘节点直连回源：
  nginx 无法解码查询参数里 percent-encoded 的目标 URL，路径段则经
  请求解析原生解码，白名单正则可直接匹配主机字面量。

GET /api/media/x/poster?url=<https-video-url>
  视频封面：twitter-cli 不落 media_url_https，库里只有 mp4 直链，前端
  点击播放占位需要真封面。X 的 mp4 是 faststart（moov 在文件头），
  拉取前 4MB 即可由 ffmpeg 抽出首帧；结果按 URL 哈希落盘缓存，新老
  数据通吃、无需回填。抽帧失败/上游 404 记入短时负缓存（5 分钟），
  避免每次渲染重复回源。匿名 IP 级限速约束生成路径（每次缓存 miss
  代价 = 4MB 回源 + ffmpeg 抽帧）：边缘 nginx 缓存命中不到应用层，
  应用层只防 miss 放大，磁盘/负缓存命中不计费。

共用约束：
  - 仅放行 twimg 主机白名单，防 SSRF 开放代理
  - 公开访问（与 /api/media/papers 静态挂载一致：媒体本身是公开内容，
    且 <img>/<video> 标签无法携带 Authorization 头）

出站代理取 env：OUTBOUND_PROXY > HTTPS_PROXY/https_proxy > ALL_PROXY/all_proxy；
未配置时直连（开发机网络不受限场景）。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from pathlib import Path
from typing import AsyncGenerator
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import FileResponse, StreamingResponse

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
        "pbs.twimg.com",
        "video.twimg.com",
        "abs.twimg.com",
    }
)

_PASSTHROUGH_REQUEST_HEADERS = ("range", "if-none-match", "if-modified-since")
_PASSTHROUGH_RESPONSE_HEADERS = (
    "content-type",
    "content-length",
    "content-range",
    "accept-ranges",
    "etag",
    "last-modified",
)

# 桌面浏览器 UA：X CDN 对明显的脚本 UA 有概率直接断连
_UPSTREAM_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

# twimg URL 内容寻址不可变（媒体 ID 在路径里），缓存一周与封面端点同口径；
# 拉长 TTL 显著降低边缘/浏览器回源频率（X 看板每日换新，URL 全是新的，
# 86400 口径下边缘缓存天然低命中，每张新图都要全链路回源）。
_CACHE_CONTROL = "public, max-age=604800"


def validate_media_url(raw_url: str) -> str:
    """校验并返回可代理的媒体 URL；任何偏离白名单的输入直接 4xx。"""
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


def _outbound_proxy() -> str | None:
    for key in ("OUTBOUND_PROXY", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


_shared_client: httpx.AsyncClient | None = None


def _get_upstream_client() -> httpx.AsyncClient:
    """返回进程级共享客户端：连接池复用 TCP+TLS+socks 会话。

    瀑布流页面一次渲染会并发拉取数十个媒体，每请求新建客户端意味着
    每次都完整握手（经 socks 代理时尤其慢）。共享客户端经 keepalive
    复用连接，是页面加载延迟的主要来源优化。

    测试缝：单测 monkeypatch 此函数注入 mock transport 客户端。
    事件循环内无 await 的原子区，首次并发创建至多浪费一个实例，无需锁。
    """
    global _shared_client
    if _shared_client is None:
        _shared_client = httpx.AsyncClient(
            proxy=_outbound_proxy(),
            timeout=httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=64, max_keepalive_connections=32),
        )
    return _shared_client


async def _stream_media(request: Request, target: str) -> StreamingResponse:
    """流式转发 twimg 媒体：透传 Range（视频 seek 依赖 206），上游状态码
    原样回传；3xx 不跟随（跟随会放开白名单约束，统一按 502）。"""
    upstream_headers = {"User-Agent": _UPSTREAM_USER_AGENT}
    for name in _PASSTHROUGH_REQUEST_HEADERS:
        value = request.headers.get(name)
        if value:
            upstream_headers[name] = value

    client = _get_upstream_client()
    try:
        upstream_request = client.build_request("GET", target, headers=upstream_headers)
        upstream = await client.send(upstream_request, stream=True)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="media upstream timeout") from exc
    except httpx.HTTPError as exc:
        logger.warning("[XMediaProxy] upstream connect failed: %s", exc)
        raise HTTPException(status_code=502, detail="media upstream unreachable") from exc

    if 300 <= upstream.status_code < 400:
        await upstream.aclose()
        logger.warning(
            "[XMediaProxy] unexpected redirect %s for %s",
            upstream.status_code,
            target,
        )
        raise HTTPException(status_code=502, detail="media upstream redirect rejected")

    response_headers = {
        name: upstream.headers[name]
        for name in _PASSTHROUGH_RESPONSE_HEADERS
        if name in upstream.headers
    }
    response_headers["Cache-Control"] = _CACHE_CONTROL

    async def body_stream() -> AsyncGenerator[bytes, None]:
        try:
            async for chunk in upstream.aiter_bytes(64 * 1024):
                yield chunk
        finally:
            # 共享客户端不随请求关闭；仅释放本响应，连接归还连接池
            await upstream.aclose()

    return StreamingResponse(
        body_stream(),
        status_code=upstream.status_code,
        headers=response_headers,
    )


@router.get("/media/x/proxy")
async def proxy_x_media(request: Request, url: str = Query(..., min_length=1)):
    target = validate_media_url(url)
    return await _stream_media(request, target)


@router.get("/media/x/img/{host}/{path:path}")
async def proxy_x_media_path(request: Request, host: str, path: str):
    """路径式媒体代理：/api/media/x/img/pbs.twimg.com/media/x.jpg?name=small。

    与查询形态 /media/x/proxy?url= 同源的第二种 wire format，供边缘节点
    直连回源：nginx 无法解码查询参数里 percent-encoded 的目标 URL（$arg_*
    不解码、rewrite 不解变量、无 lua/njs），而路径段经 nginx 请求解析原生
    解码，白名单正则可直接匹配主机字面量。目标 URL 重建后走与查询形态
    完全相同的白名单校验与流式转发，行为不变更。
    """
    raw = f"https://{host}/{path}"
    if request.url.query:
        raw = f"{raw}?{request.url.query}"
    target = validate_media_url(raw)
    return await _stream_media(request, target)


# ── 视频封面抽帧 ─────────────────────────────────────────────────────────

# faststart mp4：moov 在文件头，前 4MB 覆盖 moov + 首个 GOP，足够抽首帧
_POSTER_PARTIAL_BYTES = 4 * 1024 * 1024
_POSTER_CACHE_CONTROL = "public, max-age=604800"  # 封面按 URL 永久不变，缓存一周
_POSTER_NEGATIVE_TTL_SECONDS = 300.0
_FFMPEG_TIMEOUT_SECONDS = 30.0

# 匿名 IP 级生成限速：每次缓存 miss 代价是 4MB 回源 + ffmpeg 抽帧。
# 30 次/10 分钟对齐既有匿名端点量级（MCP 匿名 tool_call 30/min 的高代价
# 口径）；磁盘缓存/负缓存命中不计费，正常浏览重复渲染不消耗配额。
_POSTER_GENERATE_RATE_LIMIT = 30
_POSTER_RATE_LIMIT_WINDOW_SECONDS = 600

_poster_locks: dict[str, asyncio.Lock] = {}
_poster_negative: dict[str, float] = {}  # url -> 负缓存过期时刻（time.monotonic）


def _poster_cache_dir() -> Path:
    """封面缓存目录（测试缝：monkeypatch 到 tmp_path）。"""
    path = Path(settings.x_media_cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _poster_cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return _poster_cache_dir() / f"{digest}.jpg"


async def _fetch_partial(url: str) -> bytes:
    """拉取视频文件头部；非 200/206 抛 HTTPException 由路由映射。"""
    client = _get_upstream_client()
    headers = {
        "User-Agent": _UPSTREAM_USER_AGENT,
        "Range": f"bytes=0-{_POSTER_PARTIAL_BYTES - 1}",
    }
    try:
        request = client.build_request("GET", url, headers=headers)
        response = await client.send(request)
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="media upstream timeout") from exc
    except httpx.HTTPError as exc:
        logger.warning("[XMediaPoster] upstream connect failed: %s", exc)
        raise HTTPException(status_code=502, detail="media upstream unreachable") from exc
    try:
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="media upstream not found")
        if response.status_code not in (200, 206):
            logger.warning(
                "[XMediaPoster] unexpected upstream status %s for %s",
                response.status_code,
                url,
            )
            raise HTTPException(status_code=502, detail="media upstream error")
        return response.content
    finally:
        await response.aclose()


async def _run_ffmpeg_once(src: Path, tmp_out: Path, extra_args: list[str]) -> bool:
    """执行一次抽帧；成功标志：退出码 0 且输出为非空文件。"""
    import imageio_ffmpeg

    proc = await asyncio.create_subprocess_exec(
        imageio_ffmpeg.get_ffmpeg_exe(),
        "-nostdin", "-v", "error",
        *extra_args,
        "-i", str(src),
        "-frames:v", "1", "-q:v", "4",
        "-y", str(tmp_out),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_FFMPEG_TIMEOUT_SECONDS
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        logger.warning("[XMediaPoster] ffmpeg timeout for %s", src.name)
        return False
    if proc.returncode != 0:
        logger.warning(
            "[XMediaPoster] ffmpeg failed (%s): %s",
            proc.returncode,
            stderr.decode(errors="replace")[:300],
        )
        return False
    return tmp_out.exists() and tmp_out.stat().st_size > 0


async def _extract_first_frame(partial_mp4: bytes, out_path: Path) -> bool:
    """用 imageio-ffmpeg 自带的静态 ffmpeg 从部分 mp4 抽帧（测试缝）。

    优先取 1 秒处的帧：许多视频首帧是黑场/渐入，1 秒处更接近 X 官方
    封面语义；前缀不足 1 秒（短视频或高码率）时回退第 0 帧。
    输入经临时文件喂给 ffmpeg（部分 mp4 无法稳定走管道协议探测）。
    """
    work_dir = out_path.parent
    src = work_dir / f".{out_path.stem}.src.mp4"
    tmp_out = work_dir / f".{out_path.stem}.tmp.jpg"
    src.write_bytes(partial_mp4)
    try:
        for seek_args in (["-ss", "1"], []):
            if await _run_ffmpeg_once(src, tmp_out, seek_args):
                tmp_out.replace(out_path)  # 原子落盘，避免并发读到半成品
                return True
            tmp_out.unlink(missing_ok=True)
        return False
    finally:
        src.unlink(missing_ok=True)
        tmp_out.unlink(missing_ok=True)


def _poster_file_response(path: Path) -> FileResponse:
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": _POSTER_CACHE_CONTROL},
    )


def _mark_poster_negative(url: str) -> None:
    _poster_negative[url] = time.monotonic() + _POSTER_NEGATIVE_TTL_SECONDS
    prune_expired_entries(_poster_negative)


async def _enforce_poster_generate_rate_limit(request: Request) -> None:
    """生成路径的匿名 IP 级限速；Redis 不可用时放行（与既有端点同口径）。"""
    redis_client = getattr(request.app.state, "redis", None)
    if redis_client is None:
        return
    try:
        await hit_rate_limit(
            redis_client,
            action="x_media_poster_generate",
            identity=client_ip_from_request(request),
            limit=_POSTER_GENERATE_RATE_LIMIT,
            window_seconds=_POSTER_RATE_LIMIT_WINDOW_SECONDS,
        )
    except RateLimitExceededError as exc:
        raise HTTPException(
            status_code=429,
            detail="poster generation rate limited, retry later",
            headers={"Retry-After": str(_POSTER_RATE_LIMIT_WINDOW_SECONDS)},
        ) from exc
    except Exception:
        logger.warning(
            "[XMediaPoster] rate limit check failed, allowing request",
            exc_info=True,
        )


@router.get("/media/x/poster")
async def x_media_poster(request: Request, url: str = Query(..., min_length=1)):
    target = validate_media_url(url)

    cache_path = _poster_cache_path(target)
    if cache_path.exists():
        return _poster_file_response(cache_path)

    if _poster_negative.get(target, 0.0) > time.monotonic():
        raise HTTPException(status_code=404, detail="poster unavailable")

    lock = _poster_locks.setdefault(target, asyncio.Lock())
    async with lock:
        try:
            # 双检：等待锁期间并发请求可能已生成
            if cache_path.exists():
                return _poster_file_response(cache_path)
            # 仅真实生成（回源+抽帧）才计费；缓存/负缓存命中不消耗配额
            await _enforce_poster_generate_rate_limit(request)
            try:
                partial = await _fetch_partial(target)
            except HTTPException as exc:
                # 上游 404 是稳定态，记负缓存；超时/连接错误是瞬态不记
                if exc.status_code == 404:
                    _mark_poster_negative(target)
                raise
            if not await _extract_first_frame(partial, cache_path):
                _mark_poster_negative(target)
                raise HTTPException(status_code=404, detail="poster extraction failed")
            await enforce_cache_budget(
                _poster_cache_dir(),
                max_bytes=settings.media_cache_max_bytes,
                max_age_seconds=settings.media_cache_max_age_seconds,
            )
            return _poster_file_response(cache_path)
        finally:
            _poster_locks.pop(target, None)
