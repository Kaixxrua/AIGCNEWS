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
    if normalized_backend != "postgres":
        raise ValueError("PROJECT_CATALOG_BACKEND must be postgres")
    if outbox_capture_enabled or sync_worker_enabled:
        raise ValueError(
            "PostgreSQL-only runtime requires project catalog capture and sync disabled"
        )
    if shadow_enabled:
        raise ValueError(
            "PostgreSQL-only runtime requires PROJECT_CATALOG_SHADOW_ENABLED=false"
        )
    return normalized_backend
