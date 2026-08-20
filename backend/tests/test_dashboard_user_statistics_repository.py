from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

from backend.app.api import routes_dashboard
from backend.app.api.dependencies import get_user_account_repository
from backend.app.repositories.site_visit_repository import SiteVisitStats


class DashboardUserStatisticsRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        # InMemoryBackend._store 是类属性、跨实例共享：按测试名隔离 prefix，
        # 避免同 key 的缓存条目在测试间串扰
        FastAPICache.init(
            InMemoryBackend(), prefix=f"dashboard-contract-{self._testMethodName}"
        )

    def tearDown(self) -> None:
        FastAPICache.reset()

    def test_visitor_count_uses_injected_statistics_and_preserves_arithmetic(self) -> None:
        app = FastAPI()
        app.include_router(routes_dashboard.router, prefix="/api")
        repository = MagicMock()
        repository.get_user_count.return_value = 10
        repository.get_today_registered_user_count.return_value = 2
        visits = MagicMock()
        visits.get_visit_stats.return_value = SiteVisitStats(today_visits=5, total_visits=99)
        app.dependency_overrides[get_user_account_repository] = lambda: repository
        app.dependency_overrides[routes_dashboard.get_site_visit_repository] = lambda: visits

        response = TestClient(app).get("/api/dashboard/visitor-count")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "user_count": 12,
                "registered_users": 10,
                "today_registered_users": 2,
                "today_unique_visitors": 5,
                "today_visits": 5,
                "total_visits": 99,
            },
        )
        repository.get_user_count.assert_called_once_with()
        repository.get_today_registered_user_count.assert_called_once_with()
        visits.get_visit_stats.assert_called_once()

    def test_visitor_count_reads_current_counters_on_each_poll(self) -> None:
        app = FastAPI()
        app.include_router(routes_dashboard.router, prefix="/api")
        repository = MagicMock()
        repository.get_user_count.return_value = 10
        repository.get_today_registered_user_count.return_value = 2
        visits = MagicMock()
        visits.get_visit_stats.return_value = SiteVisitStats(today_visits=5, total_visits=99)
        app.dependency_overrides[get_user_account_repository] = lambda: repository
        app.dependency_overrides[routes_dashboard.get_site_visit_repository] = lambda: visits

        client = TestClient(app)
        first = client.get("/api/dashboard/visitor-count")
        second = client.get("/api/dashboard/visitor-count")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json(), first.json())
        # 动态访客端点不缓存：两次轮询均重新读取当前值。
        self.assertEqual(repository.get_user_count.call_count, 2)
        self.assertEqual(repository.get_today_registered_user_count.call_count, 2)
        self.assertEqual(visits.get_visit_stats.call_count, 2)


if __name__ == "__main__":
    unittest.main()
