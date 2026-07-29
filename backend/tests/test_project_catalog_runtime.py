from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.app import main
from backend.app.core.project_catalog_runtime import validate_project_catalog_runtime


@pytest.mark.parametrize(
    ("backend", "capture", "sync", "shadow", "expected"),
    [
        ("mysql", False, False, False, "mysql"),
        (" MYSQL ", True, False, True, "mysql"),
        ("mysql", True, True, True, "mysql"),
        ("postgres", False, False, False, "postgres"),
        ("postgres", True, True, False, "postgres"),
    ],
)
def test_runtime_matrix_accepts_safe_configurations(
    backend: str,
    capture: bool,
    sync: bool,
    shadow: bool,
    expected: str,
) -> None:
    assert validate_project_catalog_runtime(
        backend=backend,
        outbox_capture_enabled=capture,
        sync_worker_enabled=sync,
        shadow_enabled=shadow,
    ) == expected


@pytest.mark.parametrize("backend", ["", "sqlite", "mariadb"])
def test_runtime_matrix_rejects_unsupported_backends(backend: str) -> None:
    with pytest.raises(ValueError, match="PROJECT_CATALOG_BACKEND"):
        validate_project_catalog_runtime(
            backend=backend,
            outbox_capture_enabled=False,
            sync_worker_enabled=False,
            shadow_enabled=False,
        )


def test_runtime_matrix_rejects_mysql_sync_without_capture() -> None:
    with pytest.raises(ValueError, match="OUTBOX_CAPTURE_ENABLED=true"):
        validate_project_catalog_runtime(
            backend="mysql",
            outbox_capture_enabled=False,
            sync_worker_enabled=True,
            shadow_enabled=False,
        )


def test_runtime_matrix_rejects_postgres_sync_without_capture() -> None:
    with pytest.raises(ValueError, match="OUTBOX_CAPTURE_ENABLED=true"):
        validate_project_catalog_runtime(
            backend="postgres",
            outbox_capture_enabled=False,
            sync_worker_enabled=True,
            shadow_enabled=False,
        )


def test_runtime_matrix_rejects_postgres_shadow() -> None:
    with pytest.raises(ValueError, match="SHADOW_ENABLED=false"):
        validate_project_catalog_runtime(
            backend="postgres",
            outbox_capture_enabled=True,
            sync_worker_enabled=True,
            shadow_enabled=True,
        )


def test_lifespan_validates_before_opening_resources() -> None:
    app = SimpleNamespace(state=SimpleNamespace())
    unsafe_settings = SimpleNamespace(
        project_catalog_backend="mysql",
        project_catalog_outbox_capture_enabled=False,
        project_catalog_sync_worker_enabled=True,
        project_catalog_shadow_enabled=False,
    )

    async def run() -> None:
        with (
            patch.object(main, "settings", unsafe_settings),
            patch.object(main.asyncio, "to_thread") as to_thread,
            patch.object(main, "Redis") as redis_type,
            patch.object(main, "start_scheduler") as start_scheduler,
        ):
            with pytest.raises(ValueError, match="OUTBOX_CAPTURE_ENABLED=true"):
                async with main.lifespan(app):
                    pass
            to_thread.assert_not_called()
            redis_type.assert_not_called()
            start_scheduler.assert_not_called()

    asyncio.run(run())
