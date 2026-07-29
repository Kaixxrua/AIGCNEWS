from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.app.services.project_catalog_readiness import project_catalog_runtime_readiness


class Database:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0
        self.connection = MagicMock()

    @contextmanager
    def transaction(self):
        self.calls += 1
        if self.error:
            raise self.error
        yield self.connection


def config(
    backend: str = "postgres",
    *,
    capture: bool = False,
    sync: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        project_catalog_backend=backend,
        project_catalog_outbox_capture_enabled=capture,
        project_catalog_sync_worker_enabled=sync,
        project_catalog_shadow_enabled=False,
    )


def test_postgres_readiness_checks_only_postgres() -> None:
    postgres = Database()

    result = project_catalog_runtime_readiness(
        config=config(),
        postgres=postgres,  # type: ignore[arg-type]
    )

    assert result["runtime_ready"] is True
    assert result["scope"] == "application_runtime"
    assert postgres.calls == 1
    assert result["checks"] == {"configuration": "ok", "postgres": "ok"}


def test_readiness_rejects_legacy_runtime_without_database_calls() -> None:
    postgres = Database()

    result = project_catalog_runtime_readiness(
        config=config("mysql"),
        postgres=postgres,  # type: ignore[arg-type]
    )

    assert result["runtime_ready"] is False
    assert result["checks"] == {"configuration": "error"}
    assert postgres.calls == 0


def test_readiness_sanitizes_postgres_failure() -> None:
    postgres = Database(error=RuntimeError("postgresql://secret"))

    result = project_catalog_runtime_readiness(
        config=config(),
        postgres=postgres,  # type: ignore[arg-type]
    )

    assert result["runtime_ready"] is False
    assert result["checks"] == {"configuration": "ok"}
    assert result["error_class"] == "RuntimeError"
    assert "secret" not in str(result)
