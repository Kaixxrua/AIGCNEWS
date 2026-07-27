from __future__ import annotations

import asyncio
import unittest

from backend.app.services.vision.image_cache import ScreenshotImageCache


class SequenceClock:
    def __init__(self, *values: float) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


class MutableClock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class ScreenshotImageCacheTests(unittest.TestCase):
    def test_put_injects_id_strips_data_uri_and_preserves_write_boundary(self) -> None:
        cache = ScreenshotImageCache(
            clock=SequenceClock(200.0, 200.0),
            id_factory=lambda: "00000000-0000-0000-0000-000000000017",
        )
        cache._entries.update(
            {
                "expired": ("old", "image/gif", 199.999),
                "boundary": ("edge", "image/png", 200.0),
            }
        )

        image_id = asyncio.run(
            cache.put("data:image/png;base64,encoded-image", "image/webp")
        )

        self.assertEqual(image_id, "00000000-0000-0000-0000-000000000017")
        self.assertEqual(
            cache._entries,
            {
                "boundary": ("edge", "image/png", 200.0),
                image_id: ("encoded-image", "image/webp", 500.0),
            },
        )

    def test_get_keeps_exact_expiry_boundary_then_removes_expired_entry(self) -> None:
        clock = MutableClock(100.0)
        cache = ScreenshotImageCache(clock=clock)
        cache._entries["image-id"] = ("image", "image/png", 100.0)

        self.assertEqual(
            asyncio.run(cache.get("image-id")),
            ("image", "image/png"),
        )
        self.assertIn("image-id", cache._entries)

        clock.now = 100.0001
        self.assertIsNone(asyncio.run(cache.get("image-id")))
        self.assertNotIn("image-id", cache._entries)

    def test_missing_entry_returns_none_without_clock_or_disk_access(self) -> None:
        clock_calls = 0

        def clock() -> float:
            nonlocal clock_calls
            clock_calls += 1
            return 100.0

        cache = ScreenshotImageCache(clock=clock)

        self.assertIsNone(asyncio.run(cache.get("missing")))
        self.assertEqual(clock_calls, 0)
        self.assertFalse(hasattr(cache, "path"))
        self.assertFalse(hasattr(cache, "upload_dir"))


if __name__ == "__main__":
    unittest.main()
