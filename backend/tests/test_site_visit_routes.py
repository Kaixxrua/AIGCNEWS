from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

from backend.app.api import routes_dashboard
from backend.app.api.dependencies import get_user_account_repository
from backend.app.repositories.site_visit_repository import SiteVisitStats


class SiteVisitBeaconRouteTests(unittest.TestCase):
    """POST /api/dashboard/visit：纯次数口径 beacon，每次调用当天计数 +1。"""

    def setUp(self) -> None:
        FastAPICache.init(
            InMemoryBackend(), prefix=f"site-visit-contract-{self._testMethodName}"
        )

    def tearDown(self) -> None:
        FastAPICache.reset()

    def test_record_visit_returns_incremented_counters(self) -> None:
        app = FastAPI()
        app.include_router(routes_dashboard.router, prefix="/api")
        visits = MagicMock()
        visits.record_visit.return_value = SiteVisitStats(today_visits=8, total_visits=701)
        app.dependency_overrides[routes_dashboard.get_site_visit_repository] = lambda: visits
        redis = MagicMock()
        redis.sadd = AsyncMock(return_value=1)
        redis.ttl = AsyncMock(return_value=60)
        app.state.redis = redis

        response = TestClient(app).post(
            "/api/dashboard/visit", json={"visitor_id": "visitor-1234567890"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"today_visits": 8, "total_visits": 701})
        (day_arg, platform_arg), _ = visits.record_visit.call_args
        self.assertIsInstance(day_arg, date)
        # TestClient 默认不带浏览器 UA 特征，落入 other 桶
        self.assertEqual(platform_arg, "other")
        redis.sadd.assert_awaited_once()

    def test_duplicate_visitor_does_not_record_again(self) -> None:
        app = FastAPI()
        app.include_router(routes_dashboard.router, prefix="/api")
        visits = MagicMock()
        visits.get_visit_stats.return_value = SiteVisitStats(today_visits=8, total_visits=701)
        app.dependency_overrides[routes_dashboard.get_site_visit_repository] = lambda: visits
        redis = MagicMock()
        redis.sadd = AsyncMock(return_value=0)
        redis.ttl = AsyncMock(return_value=60)
        app.state.redis = redis

        response = TestClient(app).post(
            "/api/dashboard/visit", json={"visitor_id": "visitor-1234567890"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"today_visits": 8, "total_visits": 701})
        visits.record_visit.assert_not_called()

    def test_record_visit_classifies_user_agent_into_platform_bucket(self) -> None:
        app = FastAPI()
        app.include_router(routes_dashboard.router, prefix="/api")
        visits = MagicMock()
        visits.record_visit.return_value = SiteVisitStats(today_visits=1, total_visits=1)
        app.dependency_overrides[routes_dashboard.get_site_visit_repository] = lambda: visits
        redis = MagicMock()
        redis.sadd = AsyncMock(return_value=1)
        redis.ttl = AsyncMock(return_value=60)
        app.state.redis = redis

        iphone_ua = (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
        )
        response = TestClient(app).post(
            "/api/dashboard/visit",
            headers={"User-Agent": iphone_ua},
            json={"visitor_id": "visitor-1234567890"},
        )

        self.assertEqual(response.status_code, 200)
        (_, platform_arg), _ = visits.record_visit.call_args
        self.assertEqual(platform_arg, "ios")

    def test_automated_visit_is_recorded_as_bot_without_counting(self) -> None:
        app = FastAPI()
        app.include_router(routes_dashboard.router, prefix="/api")
        visits = MagicMock()
        visits.get_visit_stats.return_value = SiteVisitStats(today_visits=8, total_visits=701)
        app.dependency_overrides[routes_dashboard.get_site_visit_repository] = lambda: visits
        redis = MagicMock()
        redis.sadd = AsyncMock(return_value=1)
        redis.ttl = AsyncMock(return_value=60)
        app.state.redis = redis

        headless_ua = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) HeadlessChrome/148.0.0.0 Safari/537.36"
        )
        with patch.object(
            routes_dashboard.live_stats_broadcaster, "notify_live_stats_changed"
        ) as notify:
            response = TestClient(app).post(
                "/api/dashboard/visit",
                headers={"User-Agent": headless_ua},
                json={"visitor_id": "visitor-1234567890"},
            )

        self.assertEqual(response.status_code, 200)
        # 响应仍是未变动的真人计数，访问量总表不写、不推实时统计
        self.assertEqual(response.json(), {"today_visits": 8, "total_visits": 701})
        visits.record_visit.assert_not_called()
        (day_arg,), _ = visits.record_automated_visit.call_args
        self.assertIsInstance(day_arg, date)
        notify.assert_not_called()

    def test_linux_desktop_visit_counts_into_linux_bucket(self) -> None:
        app = FastAPI()
        app.include_router(routes_dashboard.router, prefix="/api")
        visits = MagicMock()
        visits.record_visit.return_value = SiteVisitStats(today_visits=1, total_visits=1)
        app.dependency_overrides[routes_dashboard.get_site_visit_repository] = lambda: visits
        redis = MagicMock()
        redis.sadd = AsyncMock(return_value=1)
        redis.ttl = AsyncMock(return_value=60)
        app.state.redis = redis

        linux_ua = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        )
        response = TestClient(app).post(
            "/api/dashboard/visit",
            headers={"User-Agent": linux_ua},
            json={"visitor_id": "visitor-1234567890"},
        )

        self.assertEqual(response.status_code, 200)
        (_, platform_arg), _ = visits.record_visit.call_args
        self.assertEqual(platform_arg, "linux")
        visits.record_automated_visit.assert_not_called()

    def test_visit_stats_failure_falls_back_to_zero_on_read_endpoints(self) -> None:
        """计数不可用（如 0038 迁移滞后）时读端点静默为 0，不拖垮看板轮询。"""
        app = FastAPI()
        app.include_router(routes_dashboard.router, prefix="/api")
        repository = MagicMock()
        repository.get_user_count.return_value = 10
        repository.get_today_registered_user_count.return_value = 2
        visits = MagicMock()
        visits.get_visit_stats.side_effect = psycopg.OperationalError(
            "relation does not exist"
        )
        app.dependency_overrides[get_user_account_repository] = lambda: repository
        app.dependency_overrides[routes_dashboard.get_site_visit_repository] = lambda: visits

        response = TestClient(app).get("/api/dashboard/visitor-count")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store, max-age=0, must-revalidate")
        self.assertEqual(response.headers["pragma"], "no-cache")
        body = response.json()
        self.assertEqual(body["today_visits"], 0)
        self.assertEqual(body["total_visits"], 0)
        self.assertEqual(body["today_unique_visitors"], 0)
        # 注册用户字段不受访问计数故障影响
        self.assertEqual(body["user_count"], 12)


class SiteVisitLandingRouteTests(unittest.TestCase):
    """beacon 携带 429 提示链接的 landing_ref/landing_path 时另记一次落地来源。"""

    _HEADLESS_UA = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) HeadlessChrome/148.0.0.0 Safari/537.36"
    )

    def setUp(self) -> None:
        FastAPICache.init(
            InMemoryBackend(), prefix=f"site-landing-contract-{self._testMethodName}"
        )
        self.visits = MagicMock()
        self.visits.record_visit.return_value = SiteVisitStats(today_visits=3, total_visits=90)
        self.visits.get_visit_stats.return_value = SiteVisitStats(today_visits=3, total_visits=90)
        self.redis = MagicMock()
        self.redis.ttl = AsyncMock(return_value=60)

    def tearDown(self) -> None:
        FastAPICache.reset()

    def _post(self, body: dict, *, sadd: list, headers: dict | None = None):
        app = FastAPI()
        app.include_router(routes_dashboard.router, prefix="/api")
        app.dependency_overrides[routes_dashboard.get_site_visit_repository] = lambda: self.visits
        self.redis.sadd = AsyncMock(side_effect=sadd)
        app.state.redis = self.redis
        return TestClient(app).post("/api/dashboard/visit", json=body, headers=headers or {})

    def test_returning_visitor_from_429_link_still_records_landing(self) -> None:
        response = self._post(
            {"visitor_id": "visitor-1234567890", "landing_ref": "mcp-429-anon", "landing_path": "/mcp"},
            sadd=[0, 1],
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"today_visits": 3, "total_visits": 90})
        # 访问不重复计数，落地照记
        self.visits.record_visit.assert_not_called()
        (day_arg, source_arg, path_arg), _ = self.visits.record_landing.call_args
        self.assertIsInstance(day_arg, date)
        self.assertEqual((source_arg, path_arg), ("mcp-429-anon", "/mcp"))
        landing_key, member = self.redis.sadd.await_args_list[1].args
        self.assertTrue(landing_key.startswith("aigc:site-landing-visitors:"))
        self.assertEqual(member, "mcp-429-anon|/mcp|visitor-1234567890")

    def test_new_visitor_counts_visit_and_landing(self) -> None:
        response = self._post(
            {"visitor_id": "visitor-1234567890", "landing_ref": "api-429-daily", "landing_path": "/membership"},
            sadd=[1, 1],
        )

        self.assertEqual(response.status_code, 200)
        self.visits.record_visit.assert_called_once()
        (_, source_arg, path_arg), _ = self.visits.record_landing.call_args
        self.assertEqual((source_arg, path_arg), ("api-429-daily", "/membership"))

    def test_same_landing_twice_a_day_counts_once(self) -> None:
        response = self._post(
            {"visitor_id": "visitor-1234567890", "landing_ref": "mcp-429-anon", "landing_path": "/mcp"},
            sadd=[0, 0],
        )

        self.assertEqual(response.status_code, 200)
        self.visits.record_landing.assert_not_called()

    def test_unknown_ref_records_no_landing(self) -> None:
        for ref in ("newsletter", "mcp-429-anon.", ""):
            with self.subTest(ref=ref):
                self.visits.record_landing.reset_mock()
                response = self._post(
                    {"visitor_id": "visitor-1234567890", "landing_ref": ref, "landing_path": "/mcp"},
                    sadd=[0],
                )
                self.assertEqual(response.status_code, 200)
                self.redis.sadd.assert_awaited_once()
                self.visits.record_landing.assert_not_called()

    def test_path_outside_allow_list_is_recorded_as_other(self) -> None:
        response = self._post(
            {"visitor_id": "visitor-1234567890", "landing_ref": "mcp-429-daily", "landing_path": "/" + "x" * 255},
            sadd=[0, 1],
        )

        self.assertEqual(response.status_code, 200)
        (_, source_arg, path_arg), _ = self.visits.record_landing.call_args
        self.assertEqual((source_arg, path_arg), ("mcp-429-daily", "other"))

    def test_automated_client_records_no_landing(self) -> None:
        response = self._post(
            {"visitor_id": "visitor-1234567890", "landing_ref": "mcp-429-anon", "landing_path": "/mcp"},
            sadd=[1],
            headers={"User-Agent": self._HEADLESS_UA},
        )

        self.assertEqual(response.status_code, 200)
        self.visits.record_automated_visit.assert_called_once()
        self.redis.sadd.assert_awaited_once()
        self.visits.record_landing.assert_not_called()

    def test_landing_write_failure_keeps_visit_response(self) -> None:
        self.visits.record_landing.side_effect = psycopg.errors.UndefinedTable(
            'relation "site_landing_days" does not exist'
        )

        with self.assertLogs(routes_dashboard.logger, level="WARNING"):
            response = self._post(
                {"visitor_id": "visitor-1234567890", "landing_ref": "mcp-429-anon", "landing_path": "/mcp"},
                sadd=[1, 1],
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"today_visits": 3, "total_visits": 90})
        self.visits.record_visit.assert_called_once()

    def test_landing_redis_failure_keeps_visit_response(self) -> None:
        with self.assertLogs(routes_dashboard.logger, level="WARNING"):
            response = self._post(
                {"visitor_id": "visitor-1234567890", "landing_ref": "mcp-429-anon", "landing_path": "/mcp"},
                sadd=[1, ConnectionError("redis went away")],
            )

        self.assertEqual(response.status_code, 200)
        self.visits.record_visit.assert_called_once()
        self.visits.record_landing.assert_not_called()

    def test_beacon_without_landing_fields_is_unchanged(self) -> None:
        response = self._post({"visitor_id": "visitor-1234567890"}, sadd=[1])

        self.assertEqual(response.status_code, 200)
        self.redis.sadd.assert_awaited_once()
        self.visits.record_landing.assert_not_called()


class SiteVisitStatsReadFallbackTests(unittest.IsolatedAsyncioTestCase):
    """_get_site_visit_stats 的异常契约：只吞数据库层故障。

    编程错误（直调方误传 Depends 默认值/None）必须抛出——吞掉会把 0
    静默写进 3600s 缓存（2026-08-13 预热污染生产看板事故的根因）。
    """

    async def test_db_error_falls_back_to_zero(self) -> None:
        visits = MagicMock()
        visits.get_visit_stats.side_effect = psycopg.OperationalError("db down")

        stats = await routes_dashboard._get_site_visit_stats(visits)

        self.assertEqual(stats, SiteVisitStats(today_visits=0, total_visits=0))

    async def test_programming_error_propagates(self) -> None:
        with self.assertRaises(AttributeError):
            await routes_dashboard._get_site_visit_stats(object())


if __name__ == "__main__":
    unittest.main()
