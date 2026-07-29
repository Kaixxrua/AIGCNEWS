from __future__ import annotations

from typing import Any

from backend.app.core.config import settings
from backend.app.core.postgres_database import PostgresDatabaseLifecycle, postgres_database
from backend.app.core.project_catalog_runtime import validate_project_catalog_runtime


def _ping_postgres(database: PostgresDatabaseLifecycle) -> None:
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 AS ready")
            cursor.fetchone()


def project_catalog_runtime_readiness(
    *,
    config: Any = settings,
    postgres: PostgresDatabaseLifecycle = postgres_database,
) -> dict[str, Any]:
    backend = str(getattr(config, "project_catalog_backend", "") or "").strip().lower()
    checks: dict[str, str] = {}
    try:
        backend = validate_project_catalog_runtime(
            backend=backend,
            outbox_capture_enabled=bool(
                getattr(config, "project_catalog_outbox_capture_enabled", False)
            ),
            sync_worker_enabled=bool(
                getattr(config, "project_catalog_sync_worker_enabled", False)
            ),
            shadow_enabled=bool(
                getattr(config, "project_catalog_shadow_enabled", False)
            ),
        )
        checks["configuration"] = "ok"
    except Exception as exc:
        return {
            "status": "not_ready",
            "runtime_ready": False,
            "active_backend": backend,
            "scope": "application_runtime",
            "checks": {"configuration": "error"},
            "error_class": type(exc).__name__,
        }
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
