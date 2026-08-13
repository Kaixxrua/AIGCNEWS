from __future__ import annotations

import unittest
from datetime import date
from unittest.mock import MagicMock

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

        response = TestClient(app).post("/api/dashboard/visit")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"today_visits": 8, "total_visits": 701})
        (day_arg,), _ = visits.record_visit.call_args
        self.assertIsInstance(day_arg, date)

    def test_visit_stats_failure_falls_back_to_zero_on_read_endpoints(self) -> None:
        """计数不可用（如 0038 迁移滞后）时读端点静默为 0，不拖垮看板轮询。"""
        app = FastAPI()
        app.include_router(routes_dashboard.router, prefix="/api")
        repository = MagicMock()
        repository.get_user_count.return_value = 10
        repository.get_today_registered_user_count.return_value = 2
        visits = MagicMock()
        visits.get_visit_stats.side_effect = RuntimeError("relation does not exist")
        app.dependency_overrides[get_user_account_repository] = lambda: repository
        app.dependency_overrides[routes_dashboard.get_site_visit_repository] = lambda: visits

        response = TestClient(app).get("/api/dashboard/visitor-count")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["today_visits"], 0)
        self.assertEqual(body["total_visits"], 0)
        self.assertEqual(body["today_unique_visitors"], 0)
        # 注册用户字段不受访问计数故障影响
        self.assertEqual(body["user_count"], 12)


if __name__ == "__main__":
    unittest.main()
