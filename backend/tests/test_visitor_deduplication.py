from __future__ import annotations

from datetime import date, datetime, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from backend.app.services.dashboard.visitor_deduplication import (
    InvalidVisitorId,
    landing_set_key,
    mark_new_daily_landing,
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

    async def test_landing_is_marked_per_source_path_and_visitor(self) -> None:
        redis = AsyncMock()
        redis.sadd.side_effect = [1, 0]
        redis.ttl.return_value = 60
        day = date(2026, 10, 5)

        self.assertTrue(
            await mark_new_daily_landing(
                redis, day=day, visitor_id="visitor-1234567890", source="mcp-429-anon", path="/mcp"
            )
        )
        self.assertFalse(
            await mark_new_daily_landing(
                redis, day=day, visitor_id="visitor-1234567890", source="mcp-429-anon", path="/mcp"
            )
        )
        redis.sadd.assert_any_await(landing_set_key(day), "mcp-429-anon|/mcp|visitor-1234567890")
        # 落地集合与访客集合分开：当天已来过的访客再点 429 链接仍要记落地
        self.assertNotEqual(landing_set_key(day), visitor_set_key(day))
        self.assertEqual(landing_set_key(day), "aigc:site-landing-visitors:2026-10-05")

    async def test_landing_set_repairs_missing_expiry(self) -> None:
        redis = AsyncMock()
        redis.sadd.return_value = 1
        redis.ttl.return_value = -1

        await mark_new_daily_landing(
            redis,
            day=date(2026, 10, 5),
            visitor_id="visitor-1234567890",
            source="api-429-daily",
            path="/membership",
        )

        redis.expire.assert_awaited_once()
        self.assertEqual(redis.expire.await_args.args[0], landing_set_key(date(2026, 10, 5)))

    async def test_landing_rejects_malformed_visitor_id(self) -> None:
        redis = AsyncMock()
        with self.assertRaises(InvalidVisitorId):
            await mark_new_daily_landing(
                redis, day=date(2026, 10, 5), visitor_id="bad id", source="mcp-429-anon", path="/mcp"
            )
        redis.sadd.assert_not_awaited()
