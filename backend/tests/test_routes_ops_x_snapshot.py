from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_ops
from backend.app.api.dependencies import get_x_snapshot_admin_service
from backend.app.core.auth import RequireAdmin
from backend.app.services.x_snapshot_admin import XSnapshotAdminService


def _client(service) -> TestClient:
    app = FastAPI()
    app.include_router(routes_ops.router, prefix="/api")
    app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
    app.dependency_overrides[get_x_snapshot_admin_service] = lambda: service
    return TestClient(app)


def _tomorrow_cst() -> str:
    tz_cst = timezone(timedelta(hours=8))
    return (datetime.now(tz_cst) + timedelta(days=1)).strftime("%Y-%m-%d")


class XSnapshotRebuildRouteTests(unittest.TestCase):
    def test_rebuild_all_dates_succeeds_and_clears_dashboard_cache(self) -> None:
        service = MagicMock(spec=XSnapshotAdminService)
        service.rebuild.return_value = {
            "results": [
                {"date": "2026-07-30", "upserted": 6},
                {"date": "2026-08-07", "upserted": 20},
            ],
            "skipped_no_date": 1,
        }

        with patch(
            "backend.app.api.routes_ops.clear_dashboard_cache_safely"
        ) as clear_cache:
            response = _client(service).post("/api/ops/x/snapshots/rebuild", json={})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "succeeded")
        self.assertEqual(body["skipped_no_date"], 1)
        self.assertEqual(
            body["results"],
            [
                {"date": "2026-07-30", "upserted": 6},
                {"date": "2026-08-07", "upserted": 20},
            ],
        )
        self.assertIn("26", body["message"])
        service.rebuild.assert_called_once_with(None)
        clear_cache.assert_awaited_once()

    def test_rebuild_with_target_date_passes_it_through(self) -> None:
        service = MagicMock(spec=XSnapshotAdminService)
        service.rebuild.return_value = {
            "results": [{"date": "2026-07-30", "upserted": 6}],
            "skipped_no_date": 0,
        }

        with patch(
            "backend.app.api.routes_ops.clear_dashboard_cache_safely"
        ):
            response = _client(service).post(
                "/api/ops/x/snapshots/rebuild", json={"target_date": "2026-07-30"}
            )

        self.assertEqual(response.status_code, 200)
        service.rebuild.assert_called_once_with("2026-07-30")

    def test_rebuild_rejects_malformed_date_with_400(self) -> None:
        service = MagicMock(spec=XSnapshotAdminService)

        response = _client(service).post(
            "/api/ops/x/snapshots/rebuild", json={"target_date": "2026/07/30"}
        )

        self.assertEqual(response.status_code, 400)
        service.rebuild.assert_not_called()

    def test_rebuild_rejects_future_date_with_400(self) -> None:
        service = MagicMock(spec=XSnapshotAdminService)

        response = _client(service).post(
            "/api/ops/x/snapshots/rebuild", json={"target_date": _tomorrow_cst()}
        )

        self.assertEqual(response.status_code, 400)
        service.rebuild.assert_not_called()

    def test_rebuild_without_candidates_skips_cache_clear(self) -> None:
        service = MagicMock(spec=XSnapshotAdminService)
        service.rebuild.return_value = {"results": [], "skipped_no_date": 0}

        with patch(
            "backend.app.api.routes_ops.clear_dashboard_cache_safely"
        ) as clear_cache:
            response = _client(service).post("/api/ops/x/snapshots/rebuild", json={})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])
        clear_cache.assert_not_called()

    def test_route_requires_admin_before_service_calls(self) -> None:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        service = MagicMock(spec=XSnapshotAdminService)
        app.dependency_overrides[get_x_snapshot_admin_service] = lambda: service

        response = TestClient(app).post("/api/ops/x/snapshots/rebuild", json={})

        self.assertIn(response.status_code, (401, 403))
        service.rebuild.assert_not_called()


if __name__ == "__main__":
    unittest.main()
