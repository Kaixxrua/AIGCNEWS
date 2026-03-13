from __future__ import annotations

import time
from typing import Any, Dict

from backend.app.core.config import settings


def _check_milvus() -> Dict[str, Any]:
    try:
        from pymilvus import connections, utility  # type: ignore

        alias = "health_check"
        connections.connect(
            alias=alias,
            host=settings.milvus_host,
            port=str(settings.milvus_port),
        )
        collections = utility.list_collections(using=alias)
        connections.disconnect(alias)
        return {"status": "ok", "collections": len(collections)}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_neo4j() -> Dict[str, Any]:
    try:
        from neo4j import GraphDatabase  # type: ignore

        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_username, settings.neo4j_password),
        )
        driver.verify_connectivity()
        driver.close()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_ollama() -> Dict[str, Any]:
    try:
        import httpx

        resp = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=3.0)
        resp.raise_for_status()
        models = resp.json().get("models", [])
        return {"status": "ok", "model_count": len(models)}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_mysql() -> Dict[str, Any]:
    try:
        import pymysql

        conn = pymysql.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_database,
            connect_timeout=3,
        )
        conn.ping(reconnect=False)
        conn.close()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def _check_redis() -> Dict[str, Any]:
    try:
        import redis

        client = redis.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            db=settings.redis_db,
            password=settings.redis_password or None,
            socket_connect_timeout=3,
            decode_responses=False,
        )
        pong = client.ping()
        client.close()
        return {"status": "ok", "ping": bool(pong)}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def run_health_checks() -> Dict[str, Any]:
    """Run all health checks and return a combined report."""
    t0 = time.monotonic()
    checks = {
        "milvus": _check_milvus(),
        "neo4j": _check_neo4j(),
        "ollama": _check_ollama(),
        "mysql": _check_mysql(),
        "redis": _check_redis(),
    }
    elapsed = round(time.monotonic() - t0, 3)

    overall = "ok" if all(c["status"] == "ok" for c in checks.values()) else "degraded"

    return {
        "status": overall,
        "elapsed_seconds": elapsed,
        "services": checks,
    }
