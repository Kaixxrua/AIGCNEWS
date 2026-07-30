from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from contextlib import suppress
from typing import Any, Dict

from backend.app.core.config import settings
from backend.app.core.postgres_database import (
    PostgresDatabaseLifecycle,
    postgres_database,
)
from backend.app.services.project_catalog_readiness import (
    project_catalog_runtime_readiness,
)


def _error_result(exc: Exception) -> Dict[str, str]:
    return {"status": "error", "detail": type(exc).__name__}


def _check_milvus() -> Dict[str, Any]:
    alias = "health_check"
    connections = None
    try:
        from pymilvus import connections, utility  # type: ignore

        connections.connect(
            alias=alias,
            host=settings.milvus_host,
            port=str(settings.milvus_port),
            timeout=3.0,
        )
        collections = utility.list_collections(using=alias, timeout=3.0)
        return {"status": "ok", "collections": len(collections)}
    except Exception as exc:
        return _error_result(exc)
    finally:
        if connections is not None:
            with suppress(Exception):
                connections.disconnect(alias)


def _check_neo4j() -> Dict[str, Any]:
    driver = None
    try:
        from neo4j import GraphDatabase  # type: ignore

        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
            connection_timeout=3.0,
        )
        driver.verify_connectivity()
        return {"status": "ok"}
    except Exception as exc:
        return _error_result(exc)
    finally:
        if driver is not None:
            with suppress(Exception):
                driver.close()


def _check_ollama() -> Dict[str, Any]:
    try:
        import httpx

        with httpx.Client(timeout=3.0, trust_env=False) as client:
            response = client.get(f"{settings.ollama_base_url}/api/tags")
            response.raise_for_status()
            models = response.json().get("models", [])
        return {"status": "ok", "model_count": len(models)}
    except Exception as exc:
        return _error_result(exc)


def _check_postgres(
    database: PostgresDatabaseLifecycle = postgres_database,
) -> Dict[str, Any]:
    try:
        with database.transaction() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 AS healthy")
                cursor.fetchone()
        return {"status": "ok"}
    except Exception as exc:
        return _error_result(exc)


def _check_redis() -> Dict[str, Any]:
    client = None
    try:
        import redis

        client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            password=settings.redis_password or None,
            socket_connect_timeout=3,
            socket_timeout=3,
            decode_responses=False,
        )
        return {"status": "ok", "ping": bool(client.ping())}
    except Exception as exc:
        return _error_result(exc)
    finally:
        if client is not None:
            with suppress(Exception):
                client.close()


HealthCheck = Callable[[], Dict[str, Any]]
ReadinessCheck = Callable[[], dict[str, Any]]


class HealthCheckService:
    """Run named infrastructure probes and project the combined status."""

    def __init__(self, checks: Mapping[str, HealthCheck]) -> None:
        self._checks = checks

    def run(self) -> Dict[str, Any]:
        started_at = time.monotonic()
        services: dict[str, Dict[str, Any]] = {}
        for name, check in self._checks.items():
            try:
                result = check()
                if not isinstance(result, dict) or result.get("status") not in {
                    "ok",
                    "error",
                }:
                    raise ValueError("invalid health check result")
                services[name] = result
            except Exception as exc:
                services[name] = _error_result(exc)
        elapsed = round(time.monotonic() - started_at, 3)
        overall = (
            "ok"
            if all(check["status"] == "ok" for check in services.values())
            else "degraded"
        )
        return {
            "status": overall,
            "elapsed_seconds": elapsed,
            "services": services,
        }


class ApplicationMonitoringRuntime:
    """Application-owned health and readiness checks."""

    def __init__(
        self,
        health_checks: HealthCheckService,
        readiness: ReadinessCheck,
    ) -> None:
        self.health_checks = health_checks
        self.readiness = readiness


def create_application_monitoring_runtime(
    *,
    postgres: PostgresDatabaseLifecycle = postgres_database,
) -> ApplicationMonitoringRuntime:
    return ApplicationMonitoringRuntime(
        HealthCheckService(
            {
                "milvus": _check_milvus,
                "neo4j": _check_neo4j,
                "ollama": _check_ollama,
                "postgres": lambda: _check_postgres(postgres),
                "redis": _check_redis,
            }
        ),
        lambda: project_catalog_runtime_readiness(postgres=postgres),
    )
