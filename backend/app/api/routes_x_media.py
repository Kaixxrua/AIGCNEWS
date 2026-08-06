"""X/Twitter 媒体流式代理：把 twimg CDN 的图片/视频经服务端转发给浏览器。

背景：X 媒体直链（pbs.twimg.com / video.twimg.com）在部分网络不可达
（video.twimg.com 常被单独封锁，图片可加载但视频无法播放）；服务端
出站走 WireGuard 网关 socks 代理可正常回源，故以同源流式代理兜底。

GET /api/media/x/proxy?url=<https-url>
  - 仅放行 twimg 主机白名单，防 SSRF 开放代理
  - 透传 Range：视频 seek 依赖 206 Partial Content
  - 上游状态码原样回传（404/416 等）；3xx 不跟随（twimg 正常不重定向，
    跟随会放开白名单约束，统一按 502 处理）
  - 公开访问（与 /api/media/papers 静态挂载一致：媒体本身是公开内容，
    且 <img>/<video> 标签无法携带 Authorization 头）

出站代理取 env：OUTBOUND_PROXY > HTTPS_PROXY/https_proxy > ALL_PROXY/all_proxy；
未配置时直连（开发机网络不受限场景）。
"""

from __future__ import annotations

import logging
import os
from typing import AsyncGenerator
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from starlette.responses import StreamingResponse

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

_CACHE_CONTROL = "public, max-age=86400"


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


@router.get("/media/x/proxy")
async def proxy_x_media(request: Request, url: str = Query(..., min_length=1)):
    target = validate_media_url(url)

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
