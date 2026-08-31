from __future__ import annotations

from datetime import date, datetime, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from backend.app.services.dashboard.visitor_deduplication import (
    InvalidVisitorId,
    mark_new_daily_visitor,
    seconds_until_next_cst_day,
    visitor_set_key,
)


class VisitorDeduplicationTests(IsolatedAsyncioTestCase):
    async def test_marks_first_id_and_reuses_it(self) -> None:
        redis = AsyncMock()
        redis.sadd.side_effect = [1, 0]
        redis.ttl.return_value = 60
        day = date(2026, 8, 31)

        self.assertTrue(await mark_new_daily_visitor(redis, day=day, visitor_id="visitor-1234567890"))
        self.assertFalse(await mark_new_daily_visitor(redis, day=day, visitor_id="visitor-1234567890"))
        redis.sadd.assert_any_await(visitor_set_key(day), "visitor-1234567890")

    async def test_repairs_missing_expiry(self) -> None:
        redis = AsyncMock()
        redis.sadd.return_value = 1
        redis.ttl.return_value = -1

        await mark_new_daily_visitor(redis, day=date(2026, 8, 31), visitor_id="visitor-1234567890")

        redis.expire.assert_awaited_once()
        self.assertGreater(redis.expire.await_args.args[1], 0)

    async def test_rejects_malformed_id(self) -> None:
        redis = AsyncMock()
        with self.assertRaises(InvalidVisitorId):
            await mark_new_daily_visitor(redis, day=date(2026, 8, 31), visitor_id="too-short")
        redis.sadd.assert_not_awaited()

    def test_expiry_is_until_next_cst_midnight(self) -> None:
        now = datetime(2026, 8, 31, 15, 59, tzinfo=timezone.utc)
        self.assertEqual(seconds_until_next_cst_day(now), 60)
