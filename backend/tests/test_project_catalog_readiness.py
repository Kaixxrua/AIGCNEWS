from __future__ import annotations

from contextlib import contextmanager
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


def test_postgres_readiness_checks_only_postgres() -> None:
    postgres = Database()

    result = project_catalog_runtime_readiness(
        postgres=postgres,  # type: ignore[arg-type]
    )

    assert result["runtime_ready"] is True
    assert result["active_backend"] == "postgres"
    assert result["scope"] == "application_runtime"
    assert postgres.calls == 1
    assert result["checks"] == {"configuration": "ok", "postgres": "ok"}


def test_readiness_sanitizes_postgres_failure() -> None:
    postgres = Database(error=RuntimeError("postgresql://secret"))

    result = project_catalog_runtime_readiness(
        postgres=postgres,  # type: ignore[arg-type]
    )

    assert result["runtime_ready"] is False
    assert result["active_backend"] == "postgres"
    assert result["checks"] == {"configuration": "ok"}
    assert result["error_class"] == "RuntimeError"
    assert "secret" not in str(result)
