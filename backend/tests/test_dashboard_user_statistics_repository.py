from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_dashboard
from backend.app.api.dependencies import get_user_account_repository


class DashboardUserStatisticsRepositoryTests(unittest.TestCase):
    def test_visitor_count_uses_injected_statistics_and_preserves_arithmetic(self) -> None:
        app = FastAPI()
        app.include_router(routes_dashboard.router, prefix="/api")
        repository = MagicMock()
        repository.get_user_count.return_value = 10
        repository.get_today_registered_user_count.return_value = 2
        app.dependency_overrides[get_user_account_repository] = lambda: repository

        response = TestClient(app).get("/api/dashboard/visitor-count")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "user_count": 12,
                "registered_users": 10,
                "today_registered_users": 2,
                "today_unique_visitors": 12,
            },
        )
        repository.get_user_count.assert_called_once_with()
        repository.get_today_registered_user_count.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
