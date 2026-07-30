from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.app.monitoring.health import (
    HealthCheckService,
    _check_milvus,
    _check_neo4j,
    _check_redis,
)


def test_health_report_preserves_order_and_success_projection() -> None:
    calls: list[str] = []

    def check(name: str, result: dict[str, object]):
        def run() -> dict[str, object]:
            calls.append(name)
            return result

        return run

    service = HealthCheckService(
        {
            "milvus": check("milvus", {"status": "ok", "collections": 2}),
            "neo4j": check("neo4j", {"status": "ok"}),
            "ollama": check("ollama", {"status": "ok", "model_count": 1}),
            "postgres": check("postgres", {"status": "ok"}),
            "redis": check("redis", {"status": "ok", "ping": True}),
        }
    )

    with patch(
        "backend.app.monitoring.health.time.monotonic",
        side_effect=[10.0, 10.1234],
    ):
        result = service.run()

    assert result["status"] == "ok"
    assert result["elapsed_seconds"] == 0.123
    assert list(result["services"]) == calls == [
        "milvus",
        "neo4j",
        "ollama",
        "postgres",
        "redis",
    ]


def test_health_report_is_degraded_when_any_check_fails() -> None:
    healthy = MagicMock(return_value={"status": "ok"})
    failed = MagicMock(return_value={"status": "error", "detail": "unavailable"})
    service = HealthCheckService({"postgres": healthy, "redis": failed})

    result = service.run()

    assert result["status"] == "degraded"
    assert result["services"]["redis"] == {
        "status": "error",
        "detail": "unavailable",
    }
    healthy.assert_called_once_with()
    failed.assert_called_once_with()


def test_health_report_isolates_and_sanitizes_unexpected_check_failure() -> None:
    def fail() -> dict[str, object]:
        raise RuntimeError("postgresql://user:secret@database/internal")

    service = HealthCheckService(
        {
            "postgres": fail,
            "redis": lambda: {"unexpected": True},
        }
    )

    result = service.run()

    assert result["status"] == "degraded"
    assert result["services"] == {
        "postgres": {"status": "error", "detail": "RuntimeError"},
        "redis": {"status": "error", "detail": "ValueError"},
    }
    assert "secret" not in str(result)


def test_milvus_probe_disconnects_after_success_and_failure() -> None:
    connections = MagicMock()
    utility = MagicMock()
    utility.list_collections.return_value = ["documents"]
    module = SimpleNamespace(connections=connections, utility=utility)

    with patch.dict(sys.modules, {"pymilvus": module}):
        assert _check_milvus() == {"status": "ok", "collections": 1}

    connections.disconnect.assert_called_once_with("health_check")
    connections.reset_mock()
    utility.list_collections.side_effect = RuntimeError("secret endpoint")

    with patch.dict(sys.modules, {"pymilvus": module}):
        assert _check_milvus() == {"status": "error", "detail": "RuntimeError"}

    connections.disconnect.assert_called_once_with("health_check")


def test_neo4j_probe_closes_driver_after_success_and_failure() -> None:
    driver = MagicMock()
    graph_database = MagicMock()
    graph_database.driver.return_value = driver
    module = SimpleNamespace(GraphDatabase=graph_database)

    with patch.dict(sys.modules, {"neo4j": module}):
        assert _check_neo4j() == {"status": "ok"}

    driver.close.assert_called_once_with()
    driver.reset_mock()
    driver.verify_connectivity.side_effect = RuntimeError("secret endpoint")

    with patch.dict(sys.modules, {"neo4j": module}):
        assert _check_neo4j() == {"status": "error", "detail": "RuntimeError"}

    driver.close.assert_called_once_with()


def test_redis_probe_closes_client_after_success_and_failure() -> None:
    client = MagicMock()
    client.ping.return_value = True
    redis_type = MagicMock(return_value=client)
    module = SimpleNamespace(Redis=redis_type)

    with patch.dict(sys.modules, {"redis": module}):
        assert _check_redis() == {"status": "ok", "ping": True}

    client.close.assert_called_once_with()
    client.reset_mock()
    client.ping.side_effect = RuntimeError("redis://:secret@cache")

    with patch.dict(sys.modules, {"redis": module}):
        assert _check_redis() == {"status": "error", "detail": "RuntimeError"}

    client.close.assert_called_once_with()
