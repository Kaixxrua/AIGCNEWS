from __future__ import annotations

"""x_poster_backfill 测试：monkeypatch x_poster_frames 的抽帧测试缝
（poster_cache_dir → tmp、fetch_partial/extract_first_frame fake），
复用 test_x_media_poster.py 的 poster_env 思路，无需 Redis。
"""

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from backend.app.services import x_poster_backfill, x_poster_frames
from backend.app.services.x_poster_backfill import backfill_missing_posters
from backend.app.services.x_poster_frames import XMediaUpstreamError

_NOW = datetime(2026, 8, 14, 4, 0, tzinfo=timezone.utc)

_VIDEO_URL = "https://video.twimg.com/amplify_video/1/vid/a.mp4"
_VIDEO_URL_2 = "https://video.twimg.com/amplify_video/2/vid/b.mp4"
_VIDEO_URL_3 = "https://video.twimg.com/amplify_video/3/vid/c.mp4"


def _docs(*urls: str) -> SimpleNamespace:
    docs = [
        {"media": [{"type": "video", "url": url}]}  # 无 poster_url 即回填候选
        for url in urls
    ]
    return SimpleNamespace(
        list_recent_by_source=lambda source, *, since_iso, until_iso=None, limit=500: docs
    )


class BackfillTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache_dir = Path(self._tmp.name)
        # 缓存目录指向 tmp；抽帧件与预算件全部换 fake，不碰真实 ffmpeg/磁盘策略
        self._patches = [
            patch.object(x_poster_frames, "poster_cache_dir", lambda: self.cache_dir),
            patch.object(
                x_poster_backfill, "enforce_cache_budget", new=AsyncMock()
            ),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def _patch_fetch(self, side_effect):
        fetch = AsyncMock(side_effect=side_effect)
        patcher = patch.object(x_poster_frames, "fetch_partial", fetch)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fetch

    def _patch_extract(self, ok: bool):
        async def fake_extract(partial: bytes, out_path: Path) -> bool:
            if ok:
                out_path.write_bytes(b"jpg")
            return ok

        patcher = patch.object(x_poster_frames, "extract_first_frame", fake_extract)
        patcher.start()
        self.addCleanup(patcher.stop)


class BackfillMissingPostersTest(BackfillTestBase):
    async def test_generates_poster_and_enforces_budget(self) -> None:
        self._patch_fetch(lambda url: b"mp4head")
        self._patch_extract(ok=True)
        result = await backfill_missing_posters(_docs(_VIDEO_URL), now=_NOW)
        self.assertEqual(
            (result.candidates, result.attempted, result.generated, result.failed),
            (1, 1, 1, 0),
        )
        self.assertEqual(len(list(self.cache_dir.glob("*.jpg"))), 1)
        x_poster_backfill.enforce_cache_budget.assert_awaited_once()

    async def test_skips_already_cached(self) -> None:
        self._patch_extract(ok=True)
        cache_path = x_poster_frames.poster_cache_path(_VIDEO_URL)
        cache_path.write_bytes(b"old")
        fetch = self._patch_fetch(lambda url: b"mp4head")
        result = await backfill_missing_posters(_docs(_VIDEO_URL), now=_NOW)
        self.assertEqual(result.attempted, 0)
        fetch.assert_not_awaited()

    async def test_max_per_run_bounds_attempts(self) -> None:
        self._patch_fetch(lambda url: b"mp4head")
        self._patch_extract(ok=True)
        result = await backfill_missing_posters(
            _docs(_VIDEO_URL, _VIDEO_URL_2, _VIDEO_URL_3), max_per_run=1, now=_NOW
        )
        self.assertEqual(result.candidates, 3)
        self.assertEqual(result.attempted, 1)

    async def test_upstream_404_writes_marker_and_skips_next_run(self) -> None:
        self._patch_fetch(
            XMediaUpstreamError(404, "media upstream not found")
        )
        self._patch_extract(ok=True)
        first = await backfill_missing_posters(_docs(_VIDEO_URL), now=_NOW)
        self.assertEqual((first.attempted, first.failed), (1, 1))
        markers = list(self.cache_dir.glob("*.failed"))
        self.assertEqual(len(markers), 1)
        self.assertIn("upstream_404", markers[0].read_text())
        # 7 天免重试期内：下一轮直接跳过，不再回源
        second = await backfill_missing_posters(
            _docs(_VIDEO_URL), now=_NOW + timedelta(hours=1)
        )
        self.assertEqual((second.attempted, second.skipped_marker), (0, 1))

    async def test_extract_failure_marker_expires_after_24h(self) -> None:
        self._patch_fetch(lambda url: b"mp4head")
        self._patch_extract(ok=False)
        first = await backfill_missing_posters(_docs(_VIDEO_URL), now=_NOW)
        self.assertEqual((first.attempted, first.failed), (1, 1))
        # 24h 内免重试
        within = await backfill_missing_posters(
            _docs(_VIDEO_URL), now=_NOW + timedelta(hours=23)
        )
        self.assertEqual((within.attempted, within.skipped_marker), (0, 1))
        # 超过 24h 重试
        after = await backfill_missing_posters(
            _docs(_VIDEO_URL), now=_NOW + timedelta(hours=25)
        )
        self.assertEqual(after.attempted, 1)

    async def test_transient_error_writes_no_marker(self) -> None:
        self._patch_fetch(XMediaUpstreamError(502, "media upstream error"))
        self._patch_extract(ok=True)
        first = await backfill_missing_posters(_docs(_VIDEO_URL), now=_NOW)
        self.assertEqual(first.failed, 1)
        self.assertEqual(list(self.cache_dir.glob("*.failed")), [])
        # 下一轮立即重试
        second = await backfill_missing_posters(
            _docs(_VIDEO_URL), now=_NOW + timedelta(minutes=1)
        )
        self.assertEqual(second.attempted, 1)

    async def test_failure_isolated_across_candidates(self) -> None:
        def fetch(url: str) -> bytes:
            if url == _VIDEO_URL:
                raise XMediaUpstreamError(404, "gone")
            return b"mp4head"

        self._patch_fetch(fetch)
        self._patch_extract(ok=True)
        result = await backfill_missing_posters(
            _docs(_VIDEO_URL, _VIDEO_URL_2), now=_NOW
        )
        self.assertEqual((result.attempted, result.generated, result.failed), (2, 1, 1))

    async def test_no_candidates_is_noop(self) -> None:
        result = await backfill_missing_posters(_docs(), now=_NOW)
        self.assertEqual(result.candidates, 0)
        x_poster_backfill.enforce_cache_budget.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
