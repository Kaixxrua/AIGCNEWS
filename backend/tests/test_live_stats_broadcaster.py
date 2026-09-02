from __future__ import annotations

import asyncio
import threading
import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from backend.app.monitoring.live_stats_broadcaster import (
    HEARTBEAT,
    LiveStatsBroadcaster,
    notify_live_stats_changed,
    set_live_stats_broadcaster,
)


class _FakeRedis:
    """最小 Redis 假实现：记录 get/set 调用，可注入故障。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.get_calls = 0
        self.set_calls = 0
        self.fail_get = False
        self.fail_set = False

    async def get(self, key: str) -> str | None:
        self.get_calls += 1
        if self.fail_get:
            raise RuntimeError("redis down")
        return self.store.get(key)

    async def set(self, key: str, value: str) -> None:
        self.set_calls += 1
        if self.fail_set:
            raise RuntimeError("redis down")
        self.store[key] = value


def _make(
    *,
    redis: _FakeRedis | None = None,
    compute: Any = None,
    mcp_probe: Any = None,
    debounce: float = 0.01,
    min_interval: float = 0.0,
    heartbeat: float = 0.05,
) -> LiveStatsBroadcaster:
    return LiveStatsBroadcaster(
        redis if redis is not None else _FakeRedis(),
        compute if compute is not None else AsyncMock(return_value={"total_documents": 1}),
        mcp_probe=mcp_probe,
        debounce_seconds=debounce,
        min_interval_seconds=min_interval,
        mcp_tick_seconds=999.0,
        safety_tick_seconds=999.0,
        heartbeat_seconds=heartbeat,
    )


class GetCurrentTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_hit_skips_redis_and_compute(self) -> None:
        redis = _FakeRedis()
        compute = AsyncMock(return_value={"total_documents": 1})
        broadcaster = _make(redis=redis, compute=compute)
        broadcaster._last_payload = {"total_documents": 9}

        self.assertEqual(await broadcaster.get_current(), {"total_documents": 9})
        self.assertEqual(redis.get_calls, 0)
        compute.assert_not_awaited()

    async def test_redis_hit_warms_memory_without_recompute(self) -> None:
        redis = _FakeRedis()
        redis.store[LiveStatsBroadcaster.REDIS_KEY] = '{"total_documents": 7}'
        compute = AsyncMock(return_value={"total_documents": 1})
        broadcaster = _make(redis=redis, compute=compute)

        self.assertEqual(await broadcaster.get_current(), {"total_documents": 7})
        self.assertEqual(broadcaster._last_payload, {"total_documents": 7})
        compute.assert_not_awaited()

    async def test_cold_start_recomputes_and_stores(self) -> None:
        redis = _FakeRedis()
        compute = AsyncMock(return_value={"total_documents": 3})
        broadcaster = _make(redis=redis, compute=compute)

        self.assertEqual(await broadcaster.get_current(), {"total_documents": 3})
        compute.assert_awaited_once()
        self.assertEqual(redis.store[LiveStatsBroadcaster.REDIS_KEY], '{"total_documents": 3}')

    async def test_recompute_failure_returns_empty_dict(self) -> None:
        broadcaster = _make(compute=AsyncMock(side_effect=RuntimeError("pg down")))
        self.assertEqual(await broadcaster.get_current(), {})

    async def test_redis_read_failure_falls_back_to_recompute(self) -> None:
        redis = _FakeRedis()
        redis.fail_get = True
        broadcaster = _make(redis=redis, compute=AsyncMock(return_value={"total_documents": 5}))
        self.assertEqual(await broadcaster.get_current(), {"total_documents": 5})

    async def test_redis_store_failure_is_non_fatal(self) -> None:
        redis = _FakeRedis()
        redis.fail_set = True
        broadcaster = _make(redis=redis, compute=AsyncMock(return_value={"total_documents": 5}))
        self.assertEqual(await broadcaster.get_current(), {"total_documents": 5})
        self.assertEqual(broadcaster._last_payload, {"total_documents": 5})


class NotifyAndRecomputeTests(unittest.IsolatedAsyncioTestCase):
    async def test_burst_notifications_collapse_into_one_recompute(self) -> None:
        compute = AsyncMock(return_value={"total_documents": 1})
        broadcaster = _make(compute=compute)
        await broadcaster.get_current()  # 预热，使后续重算只为 notify
        compute.reset_mock()

        for _ in range(5):
            broadcaster.notify("burst")
        await asyncio.sleep(0.1)
        compute.assert_awaited_once()
        await broadcaster.aclose()

    async def test_min_interval_defers_second_recompute(self) -> None:
        compute = AsyncMock(return_value={"v": 2})
        broadcaster = _make(compute=compute, debounce=0.01, min_interval=0.15)
        # 直接种入「很久以前算过」的旧值，让首个 notify 立即重算（绕过 get_current
        # 冷启动会刷新 _last_recompute_at，导致首个 notify 同样被节流）。
        broadcaster._last_payload = {"v": 1}
        broadcaster._last_recompute_at = 0.0

        broadcaster.notify("first")
        await asyncio.sleep(0.05)
        compute.assert_awaited_once()
        self.assertEqual(broadcaster._last_payload, {"v": 2})

        compute.return_value = {"v": 3}
        broadcaster.notify("second")
        await asyncio.sleep(0.05)
        # 仍在最小间隔内：不得立即重算
        compute.assert_awaited_once()
        await asyncio.sleep(0.25)
        self.assertEqual(compute.await_count, 2)
        self.assertEqual(broadcaster._last_payload, {"v": 3})
        await broadcaster.aclose()

    async def test_notify_from_worker_thread_still_schedules(self) -> None:
        compute = AsyncMock(return_value={"total_documents": 2})
        broadcaster = _make(compute=compute)
        await broadcaster.get_current()
        compute.reset_mock()

        done = threading.Event()

        def _notify() -> None:
            broadcaster.notify("worker-thread")
            done.set()

        thread = threading.Thread(target=_notify)
        thread.start()
        thread.join(timeout=2)
        self.assertTrue(done.is_set())
        await asyncio.sleep(0.1)
        compute.assert_awaited_once()
        await broadcaster.aclose()

    async def test_recompute_failure_keeps_old_value_and_skips_broadcast(self) -> None:
        redis = _FakeRedis()
        broadcaster = _make(redis=redis, compute=AsyncMock(return_value={"v": 1}))
        await broadcaster.get_current()
        set_calls = redis.set_calls

        broadcaster._compute = AsyncMock(side_effect=RuntimeError("pg down"))
        broadcaster.notify("break")
        await asyncio.sleep(0.1)
        self.assertEqual(broadcaster._last_payload, {"v": 1})
        self.assertEqual(redis.set_calls, set_calls)
        await broadcaster.aclose()

    async def test_identical_payload_is_not_stored_or_broadcast(self) -> None:
        redis = _FakeRedis()
        compute = AsyncMock(return_value={"v": 1})
        broadcaster = _make(redis=redis, compute=compute, heartbeat=0.03)
        await broadcaster.get_current()
        set_calls = redis.set_calls

        stream = broadcaster.subscribe()
        self.assertEqual(await stream.__anext__(), {"v": 1})
        broadcaster.notify("no-change")
        await asyncio.sleep(0.1)
        # 值未变：不重写 Redis、不广播（订阅者只会等到心跳）
        self.assertEqual(redis.set_calls, set_calls)
        self.assertIs(await stream.__anext__(), HEARTBEAT)
        await stream.aclose()
        await broadcaster.aclose()

    async def test_notify_after_close_is_noop(self) -> None:
        compute = AsyncMock(return_value={"v": 1})
        broadcaster = _make(compute=compute)
        await broadcaster.get_current()
        await broadcaster.aclose()
        compute.reset_mock()

        broadcaster.notify("too-late")
        await asyncio.sleep(0.05)
        compute.assert_not_awaited()


class SubscribeTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_frame_is_current_value_then_updates(self) -> None:
        compute = AsyncMock(return_value={"v": 1})
        broadcaster = _make(compute=compute)
        await broadcaster.get_current()

        stream = broadcaster.subscribe()
        self.assertEqual(await stream.__anext__(), {"v": 1})

        compute.return_value = {"v": 2}
        broadcaster.notify("update")
        self.assertEqual(await asyncio.wait_for(stream.__anext__(), timeout=1), {"v": 2})
        await stream.aclose()
        await broadcaster.aclose()

    async def test_heartbeat_yielded_when_idle(self) -> None:
        broadcaster = _make(heartbeat=0.03)
        await broadcaster.get_current()

        stream = broadcaster.subscribe()
        await stream.__anext__()
        self.assertIs(await asyncio.wait_for(stream.__anext__(), timeout=1), HEARTBEAT)
        await stream.aclose()
        await broadcaster.aclose()

    async def test_closing_stream_deregisters_subscriber(self) -> None:
        broadcaster = _make()
        await broadcaster.get_current()

        stream = broadcaster.subscribe()
        await stream.__anext__()
        self.assertEqual(len(broadcaster._subscribers), 1)
        await stream.aclose()
        self.assertEqual(len(broadcaster._subscribers), 0)
        await broadcaster.aclose()


class McpTickTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_tick_updates_only_mcp_fields_and_broadcasts(self) -> None:
        probe = AsyncMock(return_value=(100, 7))
        broadcaster = _make(compute=AsyncMock(return_value={"v": 1, "mcp_total_calls": 90, "mcp_dsh_calls": 5}), mcp_probe=probe)
        await broadcaster.get_current()

        stream = broadcaster.subscribe()
        await stream.__anext__()
        await broadcaster._mcp_tick_once()

        pushed = await asyncio.wait_for(stream.__anext__(), timeout=1)
        self.assertEqual(pushed, {"v": 1, "mcp_total_calls": 100, "mcp_dsh_calls": 7})
        self.assertEqual(broadcaster._last_payload["v"], 1)
        await stream.aclose()
        await broadcaster.aclose()

    async def test_mcp_tick_noop_when_counts_unchanged(self) -> None:
        redis = _FakeRedis()
        probe = AsyncMock(return_value=(90, 5))
        broadcaster = _make(redis=redis, compute=AsyncMock(return_value={"mcp_total_calls": 90, "mcp_dsh_calls": 5}), mcp_probe=probe)
        await broadcaster.get_current()
        set_calls = redis.set_calls

        await broadcaster._mcp_tick_once()
        self.assertEqual(redis.set_calls, set_calls)
        await broadcaster.aclose()

    async def test_mcp_tick_survives_probe_failure_and_none(self) -> None:
        probe = AsyncMock(side_effect=RuntimeError("redis down"))
        broadcaster = _make(mcp_probe=probe)
        await broadcaster.get_current()
        before = broadcaster._last_payload
        await broadcaster._mcp_tick_once()
        self.assertIs(broadcaster._last_payload, before)

        broadcaster._mcp_probe = AsyncMock(return_value=None)
        await broadcaster._mcp_tick_once()
        self.assertIs(broadcaster._last_payload, before)
        await broadcaster.aclose()

    async def test_mcp_tick_waits_for_warm_payload(self) -> None:
        probe = AsyncMock(return_value=(1, 1))
        broadcaster = _make(mcp_probe=probe)
        await broadcaster._mcp_tick_once()  # 未预热：直接跳过，不调用 probe
        probe.assert_not_awaited()
        await broadcaster.aclose()


class RunLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_warms_from_redis_and_cancels_cleanly(self) -> None:
        redis = _FakeRedis()
        redis.store[LiveStatsBroadcaster.REDIS_KEY] = '{"v": 42}'
        compute = AsyncMock(return_value={"v": 1})
        broadcaster = _make(redis=redis, compute=compute)

        task = asyncio.create_task(broadcaster.run())
        await asyncio.sleep(0.05)
        self.assertEqual(broadcaster._last_payload, {"v": 42})
        compute.assert_not_awaited()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await broadcaster.aclose()

    async def test_run_recomputes_on_cold_redis(self) -> None:
        compute = AsyncMock(return_value={"v": 1})
        broadcaster = _make(compute=compute)

        task = asyncio.create_task(broadcaster.run())
        await asyncio.sleep(0.05)
        self.assertEqual(broadcaster._last_payload, {"v": 1})
        compute.assert_awaited_once()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        await broadcaster.aclose()


class ModuleRegistryTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_live_stats_broadcaster(None)

    def test_notify_is_noop_without_broadcaster(self) -> None:
        set_live_stats_broadcaster(None)
        notify_live_stats_changed("no-op")  # 不应抛出

    def test_notify_delegates_to_bound_broadcaster(self) -> None:
        broadcaster = MagicMock()
        set_live_stats_broadcaster(broadcaster)
        notify_live_stats_changed("registered")
        broadcaster.notify.assert_called_once_with("registered")


if __name__ == "__main__":
    unittest.main()
