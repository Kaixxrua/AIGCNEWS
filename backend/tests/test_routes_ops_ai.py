from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app.api.dependencies import get_operations_runtime
from backend.app.api.routes_ops_ai import get_ai_ops, router
from backend.app.core.auth import RequireAdmin


def setup(admin=True):
    app = FastAPI()
    app.include_router(router)
    service, operations = MagicMock(), MagicMock()
    service.repository.create.return_value = str(uuid4())
    service.repository.list.return_value = []
    service.repository.config.return_value = {"enabled": False, "interval_minutes": 15}
    service.repository.get.return_value = {"status": "running"}
    def auth():
        if not admin:
            raise HTTPException(403)
        return {"role": "admin"}
    app.dependency_overrides[RequireAdmin] = auth
    app.dependency_overrides[get_ai_ops] = lambda: service
    app.dependency_overrides[get_operations_runtime] = lambda: operations
    return TestClient(app), service, operations


@pytest.mark.parametrize("method,path", [("get", "/runs"), ("post", "/runs"),
    ("put", "/config"), ("get", f"/runs/{uuid4()}"), ("post", f"/runs/{uuid4()}/cancel")])
def test_all_endpoints_require_admin(method, path):
    client, svc, operations = setup(False)
    assert getattr(client, method)("/ops/ai" + path).status_code == 403
    svc.repository.create.assert_not_called()
    operations.submit.assert_not_called()


def test_start_conflict_and_shutdown():
    client, svc, operations = setup()
    assert client.post("/ops/ai/runs").status_code == 202
    operations.submit.assert_called_once()
    svc.repository.create.return_value = None
    assert client.post("/ops/ai/runs").status_code == 409
    svc.repository.create.return_value = str(uuid4())
    operations.submit.return_value = False
    assert client.post("/ops/ai/runs").status_code == 503
    svc.repository.finish.assert_called_once()


def test_config_validation_and_missing_run():
    client, svc, _ = setup()
    assert client.put("/ops/ai/config", json={"enabled": True, "interval_minutes": 1}).status_code == 422
    assert client.put("/ops/ai/config", json={"enabled": True, "interval_minutes": 15}).status_code == 200
    svc.repository.get.return_value = None
    assert client.get(f"/ops/ai/runs/{uuid4()}").status_code == 404
