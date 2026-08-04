from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_ops
from backend.app.api.dependencies import get_x_watch_account_repository
from backend.app.core.auth import RequireAdmin
from backend.app.repositories.x_watch_repository import (
    XWatchAccountConflictError,
    XWatchAccountRepository,
)


def _row(**overrides):
    row = {
        "id": 42,
        "screen_name": "openai",
        "display_name": "OpenAI",
        "note": "",
        "enabled": True,
        "sort_order": 0,
        "last_test_status": "unknown",
        "last_test_message": "",
        "last_test_at": None,
        "created_at": None,
        "updated_at": None,
    }
    row.update(overrides)
    return row


class XWatchRouteTests(unittest.TestCase):
    @staticmethod
    def _client(repository: XWatchAccountRepository) -> TestClient:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        app.dependency_overrides[RequireAdmin] = lambda: {"role": "admin"}
        app.dependency_overrides[get_x_watch_account_repository] = lambda: repository
        return TestClient(app)

    @staticmethod
    def _payload(**overrides):
        payload = {
            "screen_name": "openai",
            "display_name": "OpenAI",
            "note": "",
            "enabled": True,
            "sort_order": 0,
        }
        payload.update(overrides)
        return payload

    def test_list_uses_injected_repository(self) -> None:
        repository = MagicMock(spec=XWatchAccountRepository)
        repository.list_x_watch_accounts.return_value = [_row()]

        response = self._client(repository).get("/api/ops/x-watch-accounts")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["screen_name"], "openai")
        repository.list_x_watch_accounts.assert_called_once_with()

    def test_create_normalizes_and_maps_duplicate_to_409(self) -> None:
        repository = MagicMock(spec=XWatchAccountRepository)
        repository.create_x_watch_account.return_value = _row()
        client = self._client(repository)

        response = client.post("/api/ops/x-watch-accounts", json=self._payload(screen_name=" @OpenAI "))

        self.assertEqual(response.status_code, 200)
        repository.create_x_watch_account.assert_called_once_with(
            {
                "screen_name": "openai",
                "display_name": "OpenAI",
                "note": "",
                "enabled": True,
                "sort_order": 0,
            }
        )

        repository.create_x_watch_account.side_effect = XWatchAccountConflictError()
        duplicate = client.post("/api/ops/x-watch-accounts", json=self._payload())
        self.assertEqual(duplicate.status_code, 409)

    def test_create_rejects_invalid_handle_with_400_before_store(self) -> None:
        repository = MagicMock(spec=XWatchAccountRepository)

        response = self._client(repository).post(
            "/api/ops/x-watch-accounts", json=self._payload(screen_name="bad handle!")
        )

        self.assertEqual(response.status_code, 400)
        repository.create_x_watch_account.assert_not_called()

    def test_update_and_delete_map_missing_row_to_404(self) -> None:
        repository = MagicMock(spec=XWatchAccountRepository)
        repository.update_x_watch_account.return_value = None
        repository.delete_x_watch_account.return_value = False
        client = self._client(repository)

        updated = client.put("/api/ops/x-watch-accounts/99", json=self._payload())
        deleted = client.delete("/api/ops/x-watch-accounts/99")

        self.assertEqual(updated.status_code, 404)
        self.assertEqual(deleted.status_code, 404)

    def test_test_endpoint_probes_and_persists_result(self) -> None:
        repository = MagicMock(spec=XWatchAccountRepository)
        repository.get_x_watch_account.return_value = _row()
        repository.update_x_watch_test_result.return_value = _row(
            last_test_status="succeeded",
            last_test_message="成功拉取 2 条近期推文",
        )
        client = self._client(repository)

        with patch(
            "backend.app.services.x_watch.probe.test_x_watch_account",
            return_value={"status": "succeeded", "message": "成功拉取 2 条近期推文"},
        ):
            response = client.post("/api/ops/x-watch-accounts/42/test")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "succeeded")
        self.assertEqual(body["account"]["last_test_status"], "succeeded")
        repository.update_x_watch_test_result.assert_called_once()

    def test_test_endpoint_maps_missing_row_to_404(self) -> None:
        repository = MagicMock(spec=XWatchAccountRepository)
        repository.get_x_watch_account.return_value = None

        response = self._client(repository).post("/api/ops/x-watch-accounts/99/test")

        self.assertEqual(response.status_code, 404)

    def test_routes_require_admin_before_repository_calls(self) -> None:
        app = FastAPI()
        app.include_router(routes_ops.router, prefix="/api")
        repository = MagicMock(spec=XWatchAccountRepository)
        app.dependency_overrides[get_x_watch_account_repository] = lambda: repository

        response = TestClient(app).get("/api/ops/x-watch-accounts")

        self.assertIn(response.status_code, (401, 403))
        repository.list_x_watch_accounts.assert_not_called()


if __name__ == "__main__":
    unittest.main()
