from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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


def config(backend: str, *, capture: bool, sync: bool) -> SimpleNamespace:
    return SimpleNamespace(
        project_catalog_backend=backend,
        project_catalog_outbox_capture_enabled=capture,
        project_catalog_sync_worker_enabled=sync,
        project_catalog_shadow_enabled=False,
    )


def test_mysql_readiness_does_not_require_postgres() -> None:
    mysql = Database()
    postgres = Database(error=RuntimeError("not used"))

    result = project_catalog_runtime_readiness(
        config=config("mysql", capture=False, sync=False),
        mysql=mysql,  # type: ignore[arg-type]
        postgres=postgres,  # type: ignore[arg-type]
    )

    assert result["runtime_ready"] is True
    assert mysql.calls == 1
    assert postgres.calls == 0


def test_postgres_readiness_requires_both_databases() -> None:
    result = project_catalog_runtime_readiness(
        config=config("postgres", capture=True, sync=True),
        mysql=Database(),  # type: ignore[arg-type]
        postgres=Database(error=RuntimeError("dsn secret")),  # type: ignore[arg-type]
    )

    assert result["runtime_ready"] is False
    assert result["error_class"] == "RuntimeError"
    assert "secret" not in str(result)


def test_postgres_readiness_rejects_dead_or_retrying_sync() -> None:
    worker = MagicMock()
    worker.status.return_value = {
        "dead": 1,
        "retry": 0,
        "pending": 0,
        "leased": 0,
        "source_captured_high_water": 7,
        "high_water": 7,
    }
    with patch(
        "backend.app.services.project_catalog_readiness.ProjectCatalogSyncWorker",
        return_value=worker,
    ):
        result = project_catalog_runtime_readiness(
            config=config("postgres", capture=True, sync=True),
            mysql=Database(),  # type: ignore[arg-type]
            postgres=Database(),  # type: ignore[arg-type]
        )

    assert result["runtime_ready"] is False
    assert result["checks"]["sync"] == "error"


def test_unsafe_runtime_is_not_ready_without_database_calls() -> None:
    mysql = Database()
    postgres = Database()

    result = project_catalog_runtime_readiness(
        config=config("postgres", capture=False, sync=False),
        mysql=mysql,  # type: ignore[arg-type]
        postgres=postgres,  # type: ignore[arg-type]
    )

    assert result["runtime_ready"] is False
    assert result["checks"] == {"configuration": "error"}
    assert mysql.calls == postgres.calls == 0
