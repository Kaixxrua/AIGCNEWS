"""磁盘媒体缓存的驱逐策略：TTL 过期清理 + 容量超限按最旧优先（LRU）淘汰。

wechat 图片代理与 X 视频封面缓存共用一个预算配置，写入成功后调用
enforce_cache_budget 触发；扫描按目录节流（默认 10 分钟一次），
驱逐失败只记日志、绝不影响请求路径。
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_EVICTION_INTERVAL_SECONDS = 600.0
_NEGATIVE_CACHE_MAX_SIZE = 4096

_last_eviction: dict[str, float] = {}  # cache_dir -> 上次扫描时刻（time.monotonic）
_eviction_locks: dict[str, asyncio.Lock] = {}


def _prune_dir(
    cache_dir: Path,
    *,
    max_bytes: int,
    max_age_seconds: float,
    now: float,
) -> tuple[int, int]:
    """同步执行驱逐，返回 (删除文件数, 释放字节数)。调用方负责放入线程。

    mtime 即落盘时刻（两类缓存写后均不再 touch），含崩溃残留的 .tmp
    半成品——超过 TTL 一并清理。
    """
    entries: list[tuple[float, int, Path]] = []
    for child in cache_dir.iterdir():
        if not child.is_file():
            continue
        try:
            stat = child.stat()
        except OSError:
            continue
        entries.append((stat.st_mtime, stat.st_size, child))

    removed = 0
    freed = 0

    def _delete(size: int, path: Path) -> None:
        nonlocal removed, freed
        try:
            path.unlink()
        except OSError:
            return
        removed += 1
        freed += size

    survivors: list[tuple[float, int, Path]] = []
    for mtime, size, path in entries:
        if now - mtime > max_age_seconds:
            _delete(size, path)
        else:
            survivors.append((mtime, size, path))

    total = sum(size for _, size, _ in survivors)
    if total > max_bytes:
        survivors.sort()  # mtime 升序：最旧的先被淘汰
        for _, size, path in survivors:
            if total <= max_bytes:
                break
            _delete(size, path)
            total -= size

    return removed, freed


async def enforce_cache_budget(
    cache_dir: Path,
    *,
    max_bytes: int,
    max_age_seconds: float,
) -> None:
    """按节流间隔对目录执行 TTL + 容量驱逐；任何失败仅记录日志。"""
    key = str(cache_dir)
    # 「从未扫描」与「monotonic≈0 时扫描过」必须可区分：缺省 0.0 会让开机
    # uptime < 600s 的进程（新拉起容器/CI runner）把首次驱逐误判成节流跳过。
    last = _last_eviction.get(key)
    if last is not None and time.monotonic() - last < _EVICTION_INTERVAL_SECONDS:
        return
    lock = _eviction_locks.setdefault(key, asyncio.Lock())
    if lock.locked():
        return  # 另一请求正在扫描，本次直接跳过
    async with lock:
        last = _last_eviction.get(key)
        if last is not None and time.monotonic() - last < _EVICTION_INTERVAL_SECONDS:
            return
        _last_eviction[key] = time.monotonic()
        try:
            removed, freed = await asyncio.to_thread(
                _prune_dir,
                cache_dir,
                max_bytes=max_bytes,
                max_age_seconds=max_age_seconds,
                now=time.time(),
            )
        except OSError as exc:
            logger.warning("[MediaCache] eviction failed for %s: %s", cache_dir, exc)
            return
        if removed:
            logger.info(
                "[MediaCache] evicted %d files (%.1f MiB) from %s",
                removed,
                freed / 1048576,
                cache_dir,
            )


def prune_expired_entries(cache: dict[str, float], *, max_size: int = _NEGATIVE_CACHE_MAX_SIZE) -> None:
    """负缓存（url -> monotonic 到期时刻）兜底：超阈值先清过期项，

    仍超则按到期时刻淘汰最早一半，防止无认证请求随机 URL 撑爆内存。
    """
    if len(cache) <= max_size:
        return
    now = time.monotonic()
    for key in [key for key, deadline in cache.items() if deadline <= now]:
        cache.pop(key, None)
    if len(cache) <= max_size:
        return
    for key, _ in sorted(cache.items(), key=lambda kv: kv[1])[: len(cache) // 2]:
        cache.pop(key, None)
