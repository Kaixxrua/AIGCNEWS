from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

"""首页实时计数的事件驱动分发器。

替代前端固定 10s 轮询：写路径在数据变化时 notify()，本类防抖重算并
整体替换 Redis 常驻值（recompute-then-swap，key 无 TTL，不存在删 key
等 MISS 的冷窗口），同时向本进程 SSE 订阅者广播新值，前端 RollingNumber
即时滚动。

- Redis 只作为跨重启的常驻副本；进程内存 _last_payload 是权威快照。
  key 故意不使用 "dashboard:" 前缀：cache_invalidation /
  DashboardCacheAdminService 会按 dashboard:* 模式清 key。
- notify() 线程安全（loop.call_soon_threadsafe），采集/富化 worker
  线程可直接同步调用；无运行 loop（CLI/单测）时只落 dirty 标记。
- MCP 调用计数由 Go 服务直写 Redis，Python 无写钩子：5s Redis-only
  diff tick 只更新 mcp_* 两个字段，不触发 PG 重算。
- 60s 全量重算为自愈兜底，覆盖未挂钩子的写路径（后台管理、人工修数）。
- 所有故障（重算失败/Redis 故障）保留旧值仅记日志，绝不穿透调用方。
"""

ComputeLiveStats = Callable[[], Awaitable[dict[str, Any]]]
McpProbe = Callable[[], Awaitable[tuple[int, int] | None]]

# SSE 心跳哨兵：subscribe() 在心跳间隔无事件时 yield 该值，由 SSE 层渲染
# 为 ": hb" 注释帧（撑住 nginx/SSH 反隧的空闲超时，并让断连写入尽快暴露）。
HEARTBEAT: None = None


class LiveStatsBroadcaster:
    REDIS_KEY = "livestats:current:v1"

    def __init__(
        self,
        redis: Any,
        compute: ComputeLiveStats,
        *,
        mcp_probe: McpProbe | None = None,
        debounce_seconds: float = 0.5,
        min_interval_seconds: float = 2.0,
        mcp_tick_seconds: float = 5.0,
        safety_tick_seconds: float = 60.0,
        heartbeat_seconds: float = 25.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._redis = redis
        self._compute = compute
        self._mcp_probe = mcp_probe
        self._debounce = debounce_seconds
        self._min_interval = min_interval_seconds
        self._mcp_tick = mcp_tick_seconds
        self._safety_tick = safety_tick_seconds
        self._heartbeat = heartbeat_seconds
        self._monotonic = monotonic
        try:
            self._loop: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        self._subscribers: set[asyncio.Queue[dict[str, Any] | None]] = set()
        self._dirty = False
        self._flush_handle: asyncio.TimerHandle | None = None
        self._recompute_lock = asyncio.Lock()
        self._last_payload: dict[str, Any] | None = None
        self._last_recompute_at = 0.0
        self._closed = False
        self._pending_tasks: set[asyncio.Task[object]] = set()

    # ── 写路径入口（同步、线程安全、绝不抛异常）──────────────────────────

    def notify(self, reason: str = "") -> None:
        """标记数据已变化并调度防抖重算；任何上下文可调，绝不抛出。"""
        try:
            self._notify_unsafe(reason)
        except Exception:  # noqa: BLE001 - 发布失败不得穿透业务写路径
            logger.warning("[LiveStats] notify 失败（%s，非致命）", reason, exc_info=True)

    def _notify_unsafe(self, reason: str) -> None:
        if self._closed:
            return
        loop = self._loop
        if loop is None or not loop.is_running():
            # CLI/单测无线程 loop：只落 dirty，由 get_current miss 路径补齐。
            self._dirty = True
            return
        if self._in_loop_thread():
            self._schedule_flush(reason)
        else:
            loop.call_soon_threadsafe(self._schedule_flush, reason)

    def _in_loop_thread(self) -> bool:
        try:
            return asyncio.get_running_loop() is self._loop
        except RuntimeError:
            return False

    def _schedule_flush(self, reason: str) -> None:
        self._dirty = True
        if reason:
            logger.debug("[LiveStats] change notified: %s", reason)
        if self._flush_handle is None:
            self._flush_handle = self._loop.call_later(self._debounce, self._flush_now)  # type: ignore[union-attr]

    def _flush_now(self) -> None:
        self._flush_handle = None
        if not self._dirty or self._closed:
            return
        elapsed = self._monotonic() - self._last_recompute_at
        if self._last_payload is not None and elapsed < self._min_interval:
            # 最小间隔节流（访问计数等高频源）：改到期重算而非丢弃。
            self._flush_handle = self._loop.call_later(  # type: ignore[union-attr]
                self._min_interval - elapsed, self._flush_now
            )
            return
        self._dirty = False
        self._spawn(self._recompute_and_publish("notify"))

    def _spawn(self, coro: Awaitable[object]) -> None:
        task = asyncio.create_task(coro)
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    # ── 读取与订阅 ────────────────────────────────────────────────────

    async def get_current(self) -> dict[str, Any]:
        """返回当前常驻值；内存→Redis→重算三级兜底，重算失败返回空 dict。"""
        if self._last_payload is not None:
            return self._last_payload
        cached = await self._read_redis()
        if cached is not None:
            self._last_payload = cached
            return cached
        payload = await self._recompute_and_publish("cold-start")
        return payload if payload is not None else {}

    async def subscribe(self) -> AsyncIterator[dict[str, Any] | None]:
        """首帧当前值，之后每次变更一帧；心跳间隔无事件 yield HEARTBEAT。"""
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=8)
        self._subscribers.add(queue)
        try:
            yield await self.get_current()
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=self._heartbeat)
                except TimeoutError:
                    yield HEARTBEAT
                else:
                    yield payload
        finally:
            self._subscribers.discard(queue)

    # ── 后台运行：启动预热 + MCP diff tick + 全量自愈 tick ─────────────

    async def run(self) -> None:
        """lifespan 后台 task：先 ensure-warm，再进入 tick 循环直到被取消。"""
        if self._last_payload is None:
            cached = await self._read_redis()
            if cached is not None:
                self._last_payload = cached
                logger.info("[LiveStats] 启动预热：命中 Redis 常驻值，跳过重算。")
            else:
                payload = await self._recompute_and_publish("startup-warm")
                if payload is not None:
                    logger.info("[LiveStats] 启动预热完成：Redis 常驻值已重建。")
        last_full = self._monotonic()
        while True:
            await asyncio.sleep(self._mcp_tick)
            await self._mcp_tick_once()
            if self._monotonic() - last_full >= self._safety_tick:
                last_full = self._monotonic()
                await self._recompute_and_publish("safety-tick")

    async def aclose(self) -> None:
        self._closed = True
        if self._flush_handle is not None:
            self._flush_handle.cancel()
            self._flush_handle = None
        for task in list(self._pending_tasks):
            task.cancel()
        self._subscribers.clear()

    # ── 内部实现 ──────────────────────────────────────────────────────

    async def _mcp_tick_once(self) -> None:
        """Go 侧 MCP 计数的 Redis-only diff：只动 mcp_* 两字段，不碰 PG。"""
        if self._mcp_probe is None or self._last_payload is None:
            return
        try:
            counts = await self._mcp_probe()
        except Exception:  # noqa: BLE001 - 计数探针故障静默，下 tick 重试
            return
        if counts is None:
            return
        total_calls, dsh_calls = counts
        current = self._last_payload
        if (
            int(current.get("mcp_total_calls") or 0) == total_calls
            and int(current.get("mcp_dsh_calls") or 0) == dsh_calls
        ):
            return
        updated = {
            **current,
            "mcp_total_calls": total_calls,
            "mcp_dsh_calls": dsh_calls,
        }
        self._last_payload = updated
        await self._store_redis(updated)
        self._broadcast(updated)

    async def _recompute_and_publish(self, trigger: str) -> dict[str, Any] | None:
        async with self._recompute_lock:
            try:
                payload = await self._compute()
            except Exception:  # noqa: BLE001 - 重算失败保留旧值
                logger.warning("[LiveStats] 重算失败（%s），保留旧值。", trigger, exc_info=True)
                return None
            self._last_recompute_at = self._monotonic()
        if self._last_payload is not None and payload == self._last_payload:
            return payload
        self._last_payload = payload
        await self._store_redis(payload)
        self._broadcast(payload)
        return payload

    def _broadcast(self, payload: dict[str, Any]) -> None:
        for queue in tuple(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                # 慢消费者丢帧：下一帧会带最新全量值，无累积失真。
                logger.debug("[LiveStats] 订阅者队列满，丢帧。")

    async def _read_redis(self) -> dict[str, Any] | None:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(self.REDIS_KEY)
        except Exception:  # noqa: BLE001 - Redis 故障回退重算
            logger.warning("[LiveStats] Redis 读取失败，回退重算。", exc_info=True)
            return None
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("[LiveStats] Redis 常驻值反序列化失败，回退重算。")
            return None
        return payload if isinstance(payload, dict) else None

    async def _store_redis(self, payload: dict[str, Any]) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.set(self.REDIS_KEY, json.dumps(payload, ensure_ascii=False))
        except Exception:  # noqa: BLE001 - 常驻副本失败不影响内存广播
            logger.warning("[LiveStats] Redis 常驻值写入失败（非致命）。", exc_info=True)


# ── 模块级装配（对齐 error_event_capture 的 bind 模式）──────────────────
# 仓储/服务层无法经 DI 拿到 broadcaster（它们在 lifespan 外被构造），统一走
# 模块级注册表；未装配（测试/CLI）时 notify_live_stats_changed 为 no-op。

_broadcaster: LiveStatsBroadcaster | None = None


def set_live_stats_broadcaster(broadcaster: LiveStatsBroadcaster | None) -> None:
    global _broadcaster
    _broadcaster = broadcaster


def get_live_stats_broadcaster() -> LiveStatsBroadcaster | None:
    return _broadcaster


def notify_live_stats_changed(reason: str) -> None:
    """写路径统一入口：broadcaster 未装配时静默；装配时绝不抛出。"""
    broadcaster = _broadcaster
    if broadcaster is not None:
        broadcaster.notify(reason)
