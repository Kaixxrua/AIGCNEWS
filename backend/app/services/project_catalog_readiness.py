from __future__ import annotations

import logging
from typing import Any

from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)

logger = logging.getLogger(__name__)


def _ping_postgres(database: PostgresDatabaseLifecycle) -> None:
    with database.transaction() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 AS ready")
            cursor.fetchone()


def project_catalog_runtime_readiness(
    *,
    postgres: PostgresDatabaseLifecycle = postgres_database,
) -> dict[str, Any]:
    """应用运行时就绪检查。

    error_class 仅供服务端日志与管理员诊断（ops diagnostics）使用；
    匿名可达的 /api/ready 由路由层收敛，不回传该字段。
    """
    backend = "postgres"
    checks = {"configuration": "ok"}
    try:
        _ping_postgres(postgres)
        checks["postgres"] = "ok"
    except Exception as exc:
        logger.warning(
            "[Readiness] postgres ping failed (%s): %s",
            type(exc).__name__,
            exc,
        )
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
