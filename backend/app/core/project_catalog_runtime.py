from __future__ import annotations


def validate_project_catalog_runtime(
    *,
    backend: str,
    outbox_capture_enabled: bool,
    sync_worker_enabled: bool,
    shadow_enabled: bool,
) -> str:
    """Validate the project catalog runtime matrix and return the normalized backend."""
    normalized_backend = str(backend or "").strip().lower()
    if normalized_backend not in {"mysql", "postgres"}:
        raise ValueError("PROJECT_CATALOG_BACKEND must be one of: mysql, postgres")

    if normalized_backend == "mysql" and sync_worker_enabled and not outbox_capture_enabled:
        raise ValueError(
            "MySQL project catalog sync requires "
            "PROJECT_CATALOG_OUTBOX_CAPTURE_ENABLED=true"
        )

    if normalized_backend == "postgres":
        if not outbox_capture_enabled or not sync_worker_enabled:
            raise ValueError(
                "PostgreSQL project catalog requires "
                "PROJECT_CATALOG_OUTBOX_CAPTURE_ENABLED=true and "
                "PROJECT_CATALOG_SYNC_WORKER_ENABLED=true"
            )
        if shadow_enabled:
            raise ValueError(
                "PostgreSQL project catalog requires "
                "PROJECT_CATALOG_SHADOW_ENABLED=false"
            )

    return normalized_backend
