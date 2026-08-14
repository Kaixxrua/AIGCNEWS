from __future__ import annotations

"""X 看板媒体边缘缓存预热。

冷图 MISS 要走全链路回源（边缘 → 回源通道 → 源站缓存 → twimg），实测
TTFB ~460ms；HIT 仅 ~50-80ms。新推文带来的新图永远是冷的，等用户首访
才拉就必然慢。本服务在采集完成后（以及周期兜底 job 中）对看板首屏会
真实请求的路径式代理 URL 主动 GET 边缘入口，把 proxy_cache 提前转热。

URL 形态由 x_media_urls 移植自前端渲染层，保证缓存 key 逐字节一致。
默认关闭（x_media_warmup_enabled=False）；base_url 为空时仅记日志跳过，
本地/无边缘部署不报错。
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

from backend.app.core.config import settings
from backend.app.repositories.document_repository import DocumentRecentReader
from backend.app.services.x_media_urls import collect_warmup_paths

logger = logging.getLogger(__name__)

# 与前端 x/recent 默认窗口同源的查询上限（routes_dashboard._X_RECENT_LIMIT）
_RECENT_LIMIT = 500

_warmup_client: httpx.AsyncClient | None = None


def _get_warmup_client() -> httpx.AsyncClient:
    """进程级预热客户端（测试缝：测试经 monkeypatch 替换为 MockTransport）。

    trust_env=False 是承重墙：生产宿主机的 HTTPS_PROXY/ALL_PROXY 指向
    twimg 采集 socks 链路，httpx 默认会读 env 把 localhost 边缘 GET 也
    拐进代理——预热必须直连边缘缓存入口。
    """
    global _warmup_client
    if _warmup_client is None:
        _warmup_client = httpx.AsyncClient(
            trust_env=False,
            timeout=httpx.Timeout(connect=5, read=60, write=10, pool=10),
            follow_redirects=False,
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
        )
    return _warmup_client


@dataclass(frozen=True)
class XMediaWarmupResult:
    docs_scanned: int
    urls_collected: int
    attempted: int
    ok: int  # 2xx
    failed: int  # 非 2xx（含 twimg 404 死链）+ 传输错误


_EMPTY_RESULT = XMediaWarmupResult(0, 0, 0, 0, 0)


async def _warm_one(
    client: httpx.AsyncClient, semaphore: asyncio.Semaphore, url: str
) -> bool:
    """GET 并读满响应体：HEAD 不进 proxy_cache，半截 body 会落截断缓存文件。"""
    async with semaphore:
        try:
            response = await client.get(url)
            await response.aread()
        except Exception as exc:  # noqa: BLE001 - 单 URL 故障不影响整轮
            logger.debug("[XMediaWarmup] %s 预热传输失败: %s", url, exc)
            return False
        if 200 <= response.status_code < 300:
            return True
        logger.debug("[XMediaWarmup] %s 预热返回 %s", url, response.status_code)
        return False


async def warm_recent_x_media(
    documents: DocumentRecentReader,
    *,
    base_url: str | None = None,
    window_hours: int | None = None,
    max_urls: int | None = None,
    concurrency: int | None = None,
    now: datetime | None = None,
) -> XMediaWarmupResult:
    """对滚动窗口内 X 文档的首屏媒体路径逐 GET 边缘入口，转热 proxy_cache。

    base_url 为空（未配置边缘入口）时记日志跳过，返回零值结果。
    所有单 URL 故障就地吞掉计数，整轮不抛异常（调用方是采集后台任务）。
    """
    base_url = settings.x_media_warmup_base_url if base_url is None else base_url
    window_hours = (
        settings.x_media_warmup_window_hours if window_hours is None else window_hours
    )
    max_urls = settings.x_media_warmup_max_urls if max_urls is None else max_urls
    concurrency = (
        settings.x_media_warmup_concurrency if concurrency is None else concurrency
    )
    if not base_url:
        logger.info("[XMediaWarmup] 未配置 x_media_warmup_base_url，跳过边缘预热。")
        return _EMPTY_RESULT

    started = time.monotonic()
    now = now or datetime.now(timezone.utc)
    # 存储格式为可字典序比较的 ISO 串（如 2026-08-14T03:21:10+00:00），
    # 与 routes_dashboard.get_x_recent 的 cutoff 构造保持一致
    since_iso = (now - timedelta(hours=window_hours)).isoformat(timespec="seconds")
    docs = await asyncio.to_thread(
        documents.list_recent_by_source, "x", since_iso=since_iso, limit=_RECENT_LIMIT
    )
    paths = collect_warmup_paths(docs, max_urls=max_urls)
    if not paths:
        result = XMediaWarmupResult(len(docs), 0, 0, 0, 0)
        logger.info(
            "[XMediaWarmup] 预热完成：docs=%d urls=0 ok=0 failed=0 elapsed=%.1fs",
            len(docs),
            time.monotonic() - started,
        )
        return result

    client = _get_warmup_client()
    semaphore = asyncio.Semaphore(concurrency)
    base = base_url.rstrip("/")
    outcomes = await asyncio.gather(
        *(_warm_one(client, semaphore, f"{base}{path}") for path in paths),
        return_exceptions=True,
    )
    ok = sum(1 for outcome in outcomes if outcome is True)
    failed = len(outcomes) - ok
    result = XMediaWarmupResult(len(docs), len(paths), len(paths), ok, failed)
    logger.info(
        "[XMediaWarmup] 预热完成：docs=%d urls=%d ok=%d failed=%d elapsed=%.1fs",
        result.docs_scanned,
        result.urls_collected,
        result.ok,
        result.failed,
        time.monotonic() - started,
    )
    return result


# 防 GC + 进程退出前可观测（对齐 pipeline._BACKGROUND_PDF_THREADS 模式）
_WARMUP_TASKS: set[asyncio.Task[None]] = set()


async def run_x_media_warmup_cycle(documents: DocumentRecentReader) -> None:
    """单轮预热周期：边缘缓存预热 + 存量视频封面回填（采集钩子与周期
    兜底 job 共用同一入口）。

    各段独立兜底：detached task 的异常若无人 retrieve 会打
    「Task exception was never retrieved」，预热是旁路不能让采集背锅。
    """
    try:
        await warm_recent_x_media(documents)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[XMediaWarmup] 边缘预热异常（非致命）: %s", exc, exc_info=True)
    try:
        from backend.app.services.x_poster_backfill import backfill_missing_posters

        await backfill_missing_posters(documents)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[XMediaWarmup] 封面回填异常（非致命）: %s", exc, exc_info=True)


def spawn_x_media_warmup_task(
    documents: DocumentRecentReader,
) -> asyncio.Task[None] | None:
    """采集完成后以 detached task 启动媒体预热；开关任一关闭返回 None。

    不能由调用方 await：冷图回源最坏 ~80s，会拖慢采集主流程；
    开关关闭时零行为变更。返回 task 仅供测试同步等待。
    """
    if not (settings.x_media_warmup_enabled and settings.x_source_enabled):
        return None
    task = asyncio.create_task(run_x_media_warmup_cycle(documents))
    _WARMUP_TASKS.add(task)
    task.add_done_callback(_WARMUP_TASKS.discard)
    return task
