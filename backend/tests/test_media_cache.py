"""媒体磁盘缓存驱逐策略测试。

_prune_dir 为纯同步策略函数，直接驱动；enforce_cache_budget 的节流
语义用 IsolatedAsyncioTestCase 验证；prune_expired_entries 覆盖负缓存
兜底的两段淘汰。
"""

from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from backend.app.services import media_cache
from backend.app.services.media_cache import (
    enforce_cache_budget,
    prune_expired_entries,
)


def _write_file(directory: Path, name: str, size: int, *, age_seconds: float = 0.0) -> Path:
    path = directory / name
    path.write_bytes(b"\x00" * size)
    if age_seconds:
        past = time.time() - age_seconds
        os.utime(path, (past, past))
    return path


class PruneDirTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_ttl_removes_only_expired_files(self) -> None:
        expired = _write_file(self.dir, "old.jpg", 10, age_seconds=8 * 86400)
        fresh = _write_file(self.dir, "fresh.jpg", 10)

        removed, freed = media_cache._prune_dir(
            self.dir, max_bytes=10**9, max_age_seconds=7 * 86400, now=time.time()
        )

        self.assertEqual((removed, freed), (1, 10))
        self.assertFalse(expired.exists())
        self.assertTrue(fresh.exists())

    def test_capacity_evicts_oldest_until_under_budget(self) -> None:
        oldest = _write_file(self.dir, "a.jpg", 100, age_seconds=300)
        middle = _write_file(self.dir, "b.jpg", 100, age_seconds=200)
        newest = _write_file(self.dir, "c.jpg", 100, age_seconds=100)

        removed, freed = media_cache._prune_dir(
            self.dir, max_bytes=150, max_age_seconds=10**9, now=time.time()
        )

        self.assertEqual((removed, freed), (2, 200))
        self.assertFalse(oldest.exists())
        self.assertFalse(middle.exists())
        self.assertTrue(newest.exists())

    def test_under_budget_after_ttl_leaves_survivors_untouched(self) -> None:
        kept = _write_file(self.dir, "keep.jpg", 50, age_seconds=100)

        removed, freed = media_cache._prune_dir(
            self.dir, max_bytes=10**9, max_age_seconds=10**9, now=time.time()
        )

        self.assertEqual((removed, freed), (0, 0))
        self.assertTrue(kept.exists())

    def test_skips_directories_and_vanished_files(self) -> None:
        (self.dir / "subdir").mkdir()
        _write_file(self.dir, "ok.jpg", 10)

        removed, _ = media_cache._prune_dir(
            self.dir, max_bytes=10**9, max_age_seconds=10**9, now=time.time()
        )

        self.assertEqual(removed, 0)
        self.assertTrue((self.dir / "subdir").is_dir())


class EnforceCacheBudgetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        media_cache._last_eviction.clear()
        media_cache._eviction_locks.clear()

    def tearDown(self) -> None:
        self._tmp.cleanup()
        media_cache._last_eviction.clear()
        media_cache._eviction_locks.clear()

    async def test_first_call_prunes_and_records_timestamp(self) -> None:
        expired = _write_file(self.dir, "old.jpg", 10, age_seconds=30 * 86400)

        await enforce_cache_budget(self.dir, max_bytes=10**9, max_age_seconds=7 * 86400)

        self.assertFalse(expired.exists())
        self.assertIn(str(self.dir), media_cache._last_eviction)

    async def test_second_call_within_interval_is_throttled(self) -> None:
        await enforce_cache_budget(self.dir, max_bytes=10**9, max_age_seconds=7 * 86400)
        expired = _write_file(self.dir, "late.jpg", 10, age_seconds=30 * 86400)

        await enforce_cache_budget(self.dir, max_bytes=10**9, max_age_seconds=7 * 86400)

        self.assertTrue(expired.exists(), "节流窗口内不应再次扫描")

    async def test_prune_failure_is_logged_not_raised(self) -> None:
        missing = self.dir / "does-not-exist"

        # 目录不存在时 iterdir 抛 OSError（经 to_thread 包装后按日志降级）
        await enforce_cache_budget(missing, max_bytes=10**9, max_age_seconds=7 * 86400)

        self.assertIn(str(missing), media_cache._last_eviction)


class PruneExpiredEntriesTests(unittest.TestCase):
    def test_small_cache_is_untouched(self) -> None:
        cache = {"a": time.monotonic() + 60}
        prune_expired_entries(cache, max_size=10)
        self.assertEqual(len(cache), 1)

    def test_oversized_cache_drops_expired_first(self) -> None:
        now = time.monotonic()
        cache = {f"expired-{i}": now - 1 for i in range(6)}
        cache.update({f"live-{i}": now + 60 for i in range(5)})

        prune_expired_entries(cache, max_size=10)

        self.assertEqual(len(cache), 5)
        self.assertTrue(all(key.startswith("live-") for key in cache))

    def test_still_oversized_evicts_earliest_deadlines(self) -> None:
        now = time.monotonic()
        cache = {f"key-{i}": now + i for i in range(12)}

        prune_expired_entries(cache, max_size=10)

        self.assertEqual(len(cache), 6)
        self.assertNotIn("key-0", cache)
        self.assertIn("key-11", cache)


if __name__ == "__main__":
    unittest.main()
