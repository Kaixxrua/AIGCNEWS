from __future__ import annotations

from typing import Any

from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)


def _ping_postgres(database: PostgresDatabaseLifecycle) -> None:
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 AS ready")
            cursor.fetchone()


def project_catalog_runtime_readiness(
    *,
    postgres: PostgresDatabaseLifecycle = postgres_database,
) -> dict[str, Any]:
    backend = "postgres"
    checks = {"configuration": "ok"}
    try:
        _ping_postgres(postgres)
        checks["postgres"] = "ok"
    except Exception as exc:
        return {
            "status": "not_ready",
            "runtime_ready": False,
            "active_backend": backend,
            "scope": "application_runtime",
            "checks": checks,
            "error_class": type(exc).__name__,
        }
    return {
        "status": "ready",
        "runtime_ready": True,
        "active_backend": backend,
        "scope": "application_runtime",
        "checks": checks,
        "error_class": None,
    }
