from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI

from backend.app import main
from backend.app.repositories.application_repository_context import (
    get_configured_application_repositories,
)


def test_lifespan_builds_postgres_application_composition(monkeypatch) -> None:
    repositories = MagicMock()
    monkeypatch.setattr(main, "settings", SimpleNamespace(
        project_catalog_backend="postgres",
        project_catalog_outbox_capture_enabled=False,
        project_catalog_sync_worker_enabled=False,
        project_catalog_shadow_enabled=False,
        project_semantic_search_enabled=False,
        scheduler_enabled=False,
        redis_host="unreachable",
        redis_port=6379,
        redis_db=0,
        redis_password="",
        env="test",
    ))
    factory = MagicMock(return_value=repositories)
    monkeypatch.setattr(main, "create_application_repositories", factory)
    open_pool = MagicMock()
    close_pool = MagicMock()
    monkeypatch.setattr(main.postgres_database, "open", open_pool)
    monkeypatch.setattr(main.postgres_database, "close", close_pool)
    monkeypatch.setattr(main, "Redis", MagicMock(side_effect=RuntimeError("offline")))
    monkeypatch.setattr(main, "_warmup_reranker", lambda: asyncio.sleep(0))

    app = FastAPI()

    async def exercise() -> None:
        async with main.lifespan(app):
            assert app.state.application_repositories is repositories
            assert get_configured_application_repositories() is repositories
            assert app.state.application_database_backend == "postgres"

    asyncio.run(exercise())
    with pytest.raises(RuntimeError, match="Application repositories are not configured"):
        get_configured_application_repositories()
    factory.assert_called_once_with(postgres=main.postgres_database)
    open_pool.assert_called_once_with()
    close_pool.assert_called_once_with()
