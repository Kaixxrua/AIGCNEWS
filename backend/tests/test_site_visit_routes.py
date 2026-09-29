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
