from __future__ import annotations

import asyncio
import unittest

from backend.app.services.chat import attachment_storage


class FakeClock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class ImageCacheTests(unittest.TestCase):
    def test_put_uses_600_second_ttl_and_decoded_payload_contract(self) -> None:
        clock = FakeClock(1000.0)
        cache = attachment_storage.ImageCache(clock=clock)

        expires_at = asyncio.run(cache.put("image", "encoded", "image/png"))

        self.assertEqual(expires_at, 1600.0)
        self.assertEqual(cache._entries["image"], ("encoded", "image/png", 1600.0))
        self.assertEqual(asyncio.run(cache.get("image")), ("encoded", "image/png"))

    def test_expiry_boundaries_match_existing_cache(self) -> None:
        clock = FakeClock(1000.0)
        cache = attachment_storage.ImageCache(clock=clock)
        cache._entries.update(
            {
                "expired": ("old", "image/png", 999.0),
                "boundary": ("edge", "image/png", 1000.0),
            }
        )

        asyncio.run(cache.put("new", "new-data", "image/jpeg"))

        self.assertNotIn("expired", cache._entries)
        self.assertIn("boundary", cache._entries)
        clock.now = 1600.0
        self.assertEqual(asyncio.run(cache.get("new")), ("new-data", "image/jpeg"))
        clock.now = 1600.001
        self.assertIsNone(asyncio.run(cache.get("new")))






if __name__ == "__main__":
    unittest.main()
