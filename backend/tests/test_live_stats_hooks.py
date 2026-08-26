from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

from backend.app.api import routes_dashboard
from backend.app.repositories.postgres_project_enrichment_repository import (
    PostgresGitHubProjectEnrichmentRepository,
)
from backend.app.repositories.postgres_project_ingestion_repository import (
    PostgresGitHubProjectIngestionRepository,
)
from backend.app.repositories.site_visit_repository import SiteVisitStats
from backend.app.services.auth.account_lifecycle import AccountLifecycle
from backend.app.services.dashboard import live_stats_broadcaster
from backend.app.services.ingestion import cache_invalidation
from backend.tests.test_auth_account_lifecycle import FakeOtpService, FakeRepository


class _FakeCursor:
    """吞掉所有 SQL 的游标；rowcount 可控，fetchone 默认 None。"""

    def __init__(self, *, rowcount: int = 1) -> None:
        self.rowcount = rowcount

    def execute(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def fetchone(self) -> None:
        return None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *_args: Any) -> bool:
        return False


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, *_args: Any) -> bool:
        return False


class _FakeDatabase:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def transaction(self) -> _FakeConnection:
        return _FakeConnection(self._cursor)


class LiveStatsHookTests(unittest.IsolatedAsyncioTestCase):
    """写路径 → live-stats 广播器的 notify 接线：一处漏接，前端数字就不实时。"""

    def setUp(self) -> None:
        FastAPICache.init(
            InMemoryBackend(), prefix=f"live-stats-hooks-{self._testMethodName}"
        )
        patcher = patch.object(live_stats_broadcaster, "notify_live_stats_changed")
        self.notify = patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        FastAPICache.reset()

    async def test_clear_dashboard_cache_safely_notifies(self) -> None:
        redis_client = MagicMock()
        redis_client.keys = AsyncMock(return_value=[])
        redis_client.aclose = AsyncMock()
        with patch.object(cache_invalidation, "Redis", return_value=redis_client):
            await cache_invalidation.clear_dashboard_cache_safely()
        self.notify.assert_called_once_with("dashboard-cache-cleared")

    async def test_user_registration_notifies(self) -> None:
        service = AccountLifecycle(
            repository=FakeRepository([]),
            otp=FakeOtpService([]),
            hash_password=lambda password: f"hashed:{password}",
            verify_password=lambda password, hashed: True,
            issue_token=lambda user: "token",
        )
        result = await service.register(
            email="hook@example.com", email_code="123456", password="secret-1"
        )
        self.assertEqual(result.user_id, 42)
        self.notify.assert_called_once_with("user-registered")

    async def test_site_visit_beacon_notifies(self) -> None:
        app = FastAPI()
        app.include_router(routes_dashboard.router, prefix="/api")
        visits = MagicMock()
        visits.record_visit.return_value = SiteVisitStats(today_visits=1, total_visits=2)
        app.dependency_overrides[routes_dashboard.get_site_visit_repository] = (
            lambda: visits
        )

        response = TestClient(app).post("/api/dashboard/visit")
        self.assertEqual(response.status_code, 200)
        self.notify.assert_called_once_with("site-visit")

    async def test_enrichment_upsert_notifies(self) -> None:
        repo = PostgresGitHubProjectEnrichmentRepository(database=_FakeDatabase(_FakeCursor()))
        await __import__("asyncio").to_thread(
            repo.upsert_github_repo_enrichment,
            {"repo_id": "owner/repo", "category_slug": "agent"},
        )
        self.notify.assert_called_once_with("github-enrichment-upsert")

    async def test_mark_available_notifies_only_on_state_change(self) -> None:
        repo = PostgresGitHubProjectIngestionRepository(
            database=_FakeDatabase(_FakeCursor(rowcount=1))
        )
        self.assertTrue(
            repo.mark_github_repo_available("owner/repo", checked_at="2026-08-26T00:00:00Z")
        )
        self.notify.assert_called_once_with("github-repo-available")

        self.notify.reset_mock()
        repo = PostgresGitHubProjectIngestionRepository(
            database=_FakeDatabase(_FakeCursor(rowcount=0))
        )
        self.assertFalse(
            repo.mark_github_repo_available("owner/repo", checked_at="2026-08-26T00:00:00Z")
        )
        self.notify.assert_not_called()

    async def test_record_not_found_notifies_only_when_newly_flagged(self) -> None:
        repo = PostgresGitHubProjectIngestionRepository(
            database=_FakeDatabase(_FakeCursor())
        )
        with patch.object(
            repo, "_apply_not_found_observation", return_value=(None, True)
        ):
            self.assertTrue(
                repo.record_github_repo_not_found(
                    "owner/repo", checked_at="2026-08-26T00:00:00Z"
                )
            )
        self.notify.assert_called_once_with("github-repo-not-found")

        self.notify.reset_mock()
        with patch.object(
            repo, "_apply_not_found_observation", return_value=(None, False)
        ):
            self.assertFalse(
                repo.record_github_repo_not_found(
                    "owner/repo", checked_at="2026-08-26T00:00:00Z"
                )
            )
        self.notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
