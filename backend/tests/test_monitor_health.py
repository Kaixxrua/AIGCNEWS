from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.app.monitoring.health import HealthCheckService


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
