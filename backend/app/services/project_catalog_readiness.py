from __future__ import annotations

from typing import Any

from backend.app.core.config import settings
from backend.app.core.database import DatabaseLifecycle, mysql_database
from backend.app.core.postgres_database import PostgresDatabaseLifecycle, postgres_database
from backend.app.core.project_catalog_runtime import validate_project_catalog_runtime
from backend.app.services.project_catalog_sync import ProjectCatalogSyncWorker


def _ping_mysql(database: DatabaseLifecycle) -> None:
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 AS ready")
            cursor.fetchone()


def _ping_postgres(database: PostgresDatabaseLifecycle) -> None:
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 AS ready")
            cursor.fetchone()


def project_catalog_runtime_readiness(
    *,
    config: Any = settings,
    mysql: DatabaseLifecycle = mysql_database,
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
            "scope": "public_catalog_reads_only",
            "checks": {"configuration": "error"},
            "error_class": type(exc).__name__,
        }
    try:
        _ping_mysql(mysql)
        checks["mysql"] = "ok"
        if backend == "postgres" or bool(
            getattr(config, "project_catalog_sync_worker_enabled", False)
        ):
            _ping_postgres(postgres)
            checks["postgres"] = "ok"
            sync_status = ProjectCatalogSyncWorker(
                mysql=mysql,
                postgres=postgres,
            ).status()
            source_high_water = int(
                sync_status.get("source_captured_high_water") or 0
            )
            processed_high_water = int(sync_status.get("high_water") or 0)
            checks["sync"] = (
                "ok"
                if int(sync_status.get("dead") or 0) == 0
                and int(sync_status.get("retry") or 0) == 0
                and int(sync_status.get("pending") or 0) == 0
                and int(sync_status.get("leased") or 0) == 0
                and source_high_water == processed_high_water
                else "error"
            )
            if checks["sync"] != "ok":
                raise RuntimeError("project catalog synchronization is unhealthy")
    except Exception as exc:
        return {
            "status": "not_ready",
            "runtime_ready": False,
            "active_backend": backend,
            "scope": "public_catalog_reads_only",
            "checks": checks,
            "error_class": type(exc).__name__,
        }
    return {
        "status": "ready",
        "runtime_ready": True,
        "active_backend": backend,
        "scope": "public_catalog_reads_only",
        "checks": checks,
        "error_class": None,
    }
