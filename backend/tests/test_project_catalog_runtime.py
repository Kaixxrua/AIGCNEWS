from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from backend.app import main
from backend.app.core.project_catalog_runtime import validate_project_catalog_runtime


def test_runtime_accepts_postgres_only_configuration() -> None:
    assert validate_project_catalog_runtime(
        backend=" POSTGRES ",
        outbox_capture_enabled=False,
        sync_worker_enabled=False,
        shadow_enabled=False,
    ) == "postgres"


@pytest.mark.parametrize("backend", ["", "sqlite", "mariadb", "mysql"])
def test_runtime_rejects_non_postgres_backends(backend: str) -> None:
    with pytest.raises(ValueError, match="must be postgres"):
        validate_project_catalog_runtime(
            backend=backend,
            outbox_capture_enabled=False,
            sync_worker_enabled=False,
            shadow_enabled=False,
        )


@pytest.mark.parametrize(
    ("capture", "sync"),
    [(True, False), (False, True), (True, True)],
)
def test_runtime_rejects_legacy_capture_or_sync(capture: bool, sync: bool) -> None:
    with pytest.raises(ValueError, match="capture and sync disabled"):
        validate_project_catalog_runtime(
            backend="postgres",
            outbox_capture_enabled=capture,
            sync_worker_enabled=sync,
            shadow_enabled=False,
        )


def test_runtime_rejects_shadow() -> None:
    with pytest.raises(ValueError, match="SHADOW_ENABLED=false"):
        validate_project_catalog_runtime(
            backend="postgres",
            outbox_capture_enabled=False,
            sync_worker_enabled=False,
            shadow_enabled=True,
        )


def test_lifespan_validates_before_opening_resources() -> None:
    app = SimpleNamespace(state=SimpleNamespace())
    unsafe_settings = SimpleNamespace(
        project_catalog_backend="mysql",
        project_catalog_outbox_capture_enabled=False,
        project_catalog_sync_worker_enabled=False,
        project_catalog_shadow_enabled=False,
    )

    async def run() -> None:
        with (
            patch.object(main, "settings", unsafe_settings),
            patch.object(main.asyncio, "to_thread") as to_thread,
            patch.object(main, "Redis") as redis_type,
            patch.object(main, "start_scheduler") as start_scheduler,
        ):
            with pytest.raises(ValueError, match="must be postgres"):
                async with main.lifespan(app):
                    pass
            to_thread.assert_not_called()
            redis_type.assert_not_called()
            start_scheduler.assert_not_called()

    asyncio.run(run())
