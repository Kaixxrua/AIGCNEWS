"""X 视频封面抽帧与磁盘缓存（领域件，services 层）。

从 api/routes_x_media.py 下沉：回源拉取、ffmpeg 抽帧、缓存路径计算是
纯领域逻辑，路由层（封面端点）与存量回填服务（x_poster_backfill）共用。
HTTP 语义不进本层：回源失败抛 XMediaUpstreamError 领域异常，状态码映射
由路由边界完成。

X 的 mp4 是 faststart（moov 在文件头），拉取前 4MB 即可由 ffmpeg 抽出
首帧；结果按 URL 哈希落盘缓存。

出站代理取 env：OUTBOUND_PROXY > HTTPS_PROXY/https_proxy > ALL_PROXY/all_proxy；
未配置时直连（开发机网络不受限场景）。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from pathlib import Path

import httpx

from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# faststart mp4：moov 在文件头，前 4MB 覆盖 moov + 首个 GOP，足够抽首帧
POSTER_PARTIAL_BYTES = 4 * 1024 * 1024
_FFMPEG_TIMEOUT_SECONDS = 30.0

# 桌面浏览器 UA：X CDN 对明显的脚本 UA 有概率直接断连
UPSTREAM_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


class XMediaUpstreamError(Exception):
    """twimg 回源失败的领域异常；status_code 由路由层映射为 HTTP 响应。"""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def outbound_proxy() -> str | None:
    for key in ("OUTBOUND_PROXY", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return None


_shared_client: httpx.AsyncClient | None = None


def get_upstream_client() -> httpx.AsyncClient:
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
            proxy=outbound_proxy(),
            timeout=httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0),
            follow_redirects=False,
            limits=httpx.Limits(
                max_connections=64,
                max_keepalive_connections=32,
                # The media egress can silently stop answering sockets after
                # ~2s idle. Expire them before HTTPX's default 5s reuse window;
                # otherwise the next Range waits for the full read timeout.
                keepalive_expiry=1.0,
            ),
        )
    return _shared_client


def poster_cache_dir() -> Path:
    """封面缓存目录（测试缝：monkeypatch 到 tmp_path）。"""
    path = Path(settings.x_media_cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def poster_cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
    return poster_cache_dir() / f"{digest}.jpg"


async def fetch_partial(url: str) -> bytes:
    """拉取视频文件头部；非 200/206 抛 XMediaUpstreamError 由路由层映射。"""
    client = get_upstream_client()
    headers = {
        "User-Agent": UPSTREAM_USER_AGENT,
        "Range": f"bytes=0-{POSTER_PARTIAL_BYTES - 1}",
    }
    try:
        request = client.build_request("GET", url, headers=headers)
        response = await client.send(request)
    except httpx.TimeoutException as exc:
        raise XMediaUpstreamError(504, "media upstream timeout") from exc
    except httpx.HTTPError as exc:
        logger.warning("[XMediaPoster] upstream connect failed: %s", exc)
        raise XMediaUpstreamError(502, "media upstream unreachable") from exc
    try:
        if response.status_code == 404:
            raise XMediaUpstreamError(404, "media upstream not found")
        if response.status_code not in (200, 206):
            logger.warning(
                "[XMediaPoster] unexpected upstream status %s for %s",
                response.status_code,
                url,
            )
            raise XMediaUpstreamError(502, "media upstream error")
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


async def extract_first_frame(partial_mp4: bytes, out_path: Path) -> bool:
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
