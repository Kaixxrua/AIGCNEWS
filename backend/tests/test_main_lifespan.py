from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI

from backend.app import main


def _settings(*, scheduler_enabled: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        project_semantic_search_enabled=False,
        scheduler_enabled=scheduler_enabled,
        redis_host="localhost",
        redis_port=6379,
        redis_db=0,
        redis_password="",
        env="test",
    )


class MainLifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_mounts_and_closes_postgres_lifecycle(self) -> None:
        app = FastAPI()
        database = MagicMock()
        repositories = MagicMock()
        redis_client = MagicMock()
        redis_client.ping = AsyncMock()
        redis_client.keys = AsyncMock(return_value=[])
        redis_client.aclose = AsyncMock()

        project_search_runtime = MagicMock()
        project_search_runtime.close = AsyncMock()
        rag_provider = MagicMock()
        scheduler_runtime = MagicMock()
        with (
            patch.object(main, "settings", _settings()),
            patch.object(main, "postgres_database", database),
            patch.object(main, "create_application_repositories", return_value=repositories) as factory,
            patch.object(
                main,
                "create_scheduler_runtime",
                return_value=scheduler_runtime,
            ) as scheduler_factory,
            patch.object(
                main,
                "ApplicationProjectSearchRuntime",
                return_value=project_search_runtime,
            ),
            patch.object(
                main,
                "RagChatServiceProvider",
                return_value=rag_provider,
            ) as rag_provider_type,
            patch.object(main, "Redis", return_value=redis_client),
            patch.object(main.FastAPICache, "init"),
        ):
            async with main.lifespan(app):
                self.assertIs(app.state.database, database)
                self.assertIs(app.state.postgres_database, database)
                self.assertIs(app.state.application_repositories, repositories)
                self.assertIs(app.state.scheduler_runtime, scheduler_runtime)
                self.assertIs(app.state.project_search_runtime, project_search_runtime)
                scheduler_runtime.start.assert_not_called()
                scheduler_runtime.stop.assert_not_called()
                database.close.assert_not_called()

            factory.assert_called_once_with(postgres=database)
            rag_provider_type.assert_called_once_with(
                repositories,
                project_searcher=project_search_runtime.search_projects,
            )
            scheduler_factory.assert_called_once_with(
                repositories,
                enabled=False,
                semantic_search_warmup=project_search_runtime.warmup_semantic_search,
            )
            scheduler_runtime.start.assert_not_called()
            scheduler_runtime.stop.assert_called_once_with()
            project_search_runtime.close.assert_awaited_once_with()
            rag_provider.close.assert_called_once_with()
            redis_client.aclose.assert_awaited_once_with()
            database.close.assert_called_once_with()

    async def test_disabled_scheduler_ignores_invalid_timezone(self) -> None:
        app = FastAPI()
        database = MagicMock()
        redis_client = MagicMock()
        redis_client.ping = AsyncMock()
        redis_client.keys = AsyncMock(return_value=[])
        redis_client.aclose = AsyncMock()
        warmup_task = MagicMock()
        warmup_task.done.return_value = True
        configured_settings = _settings()
        configured_settings.scheduler_timezone = "not-a-timezone"

        def close_warmup_coroutine(coroutine):
            coroutine.close()
            return warmup_task

        with (
            patch.object(main, "settings", configured_settings),
            patch.object(main, "postgres_database", database),
            patch.object(
                main,
                "create_application_repositories",
                return_value=MagicMock(),
            ),
            patch.object(main, "Redis", return_value=redis_client),
            patch.object(main.FastAPICache, "init"),
            patch.object(
                main.asyncio,
                "create_task",
                side_effect=close_warmup_coroutine,
            ),
        ):
            async with main.lifespan(app):
                self.assertFalse(app.state.scheduler_runtime.scheduler.running)

        redis_client.aclose.assert_awaited_once_with()
        database.close.assert_called_once_with()

    async def test_starts_and_stops_enabled_application_scheduler(self) -> None:
        app = FastAPI()
        database = MagicMock()
        repositories = MagicMock()
        scheduler_runtime = MagicMock()
        project_search_runtime = MagicMock()
        project_search_runtime.close = AsyncMock()
        redis_client = MagicMock()
        redis_client.ping = AsyncMock()
        redis_client.keys = AsyncMock(return_value=[])
        redis_client.aclose = AsyncMock()
        warmup_task = MagicMock()
        warmup_task.done.return_value = True

        def close_warmup_coroutine(coroutine):
            coroutine.close()
            return warmup_task

        with (
            patch.object(main, "settings", _settings(scheduler_enabled=True)),
            patch.object(main, "postgres_database", database),
            patch.object(
                main,
                "create_application_repositories",
                return_value=repositories,
            ),
            patch.object(
                main,
                "create_scheduler_runtime",
                return_value=scheduler_runtime,
            ) as scheduler_factory,
            patch.object(
                main,
                "ApplicationProjectSearchRuntime",
                return_value=project_search_runtime,
            ),
            patch.object(main, "Redis", return_value=redis_client),
            patch.object(main.FastAPICache, "init"),
            patch.object(
                main.asyncio,
                "create_task",
                side_effect=close_warmup_coroutine,
            ),
        ):
            async with main.lifespan(app):
                self.assertIs(app.state.scheduler_runtime, scheduler_runtime)
                scheduler_runtime.start.assert_called_once_with()
                scheduler_runtime.stop.assert_not_called()

        scheduler_factory.assert_called_once_with(
            repositories,
            enabled=True,
            semantic_search_warmup=project_search_runtime.warmup_semantic_search,
        )
        scheduler_runtime.stop.assert_called_once_with()
        project_search_runtime.close.assert_awaited_once_with()

    async def test_cancels_unfinished_semantic_warmup_on_shutdown(self) -> None:
        app = FastAPI()
        database = MagicMock()
        redis_client = MagicMock()
        redis_client.ping = AsyncMock()
        redis_client.keys = AsyncMock(return_value=[])
        redis_client.aclose = AsyncMock()
        pending = asyncio.get_running_loop().create_future()

        def close_warmup_coroutine(coroutine):
            coroutine.close()
            return pending

        configured_settings = _settings()
        configured_settings.project_semantic_search_enabled = True
        with (
            patch.object(main, "settings", configured_settings),
            patch.object(main, "postgres_database", database),
            patch.object(main, "create_application_repositories", return_value=MagicMock()),
            patch.object(main, "Redis", return_value=redis_client),
            patch.object(main.FastAPICache, "init"),
            patch.object(main.asyncio, "create_task", side_effect=close_warmup_coroutine),
        ):
            async with main.lifespan(app):
                self.assertIs(app.state.semantic_warmup_task, pending)

        self.assertTrue(pending.cancelled())

    async def test_closes_postgres_when_redis_initialization_fails(self) -> None:
        app = FastAPI()
        database = MagicMock()
        redis_client = MagicMock()
        redis_client.ping = AsyncMock(side_effect=RuntimeError("redis unavailable"))
        redis_client.aclose = AsyncMock()

        warmup_task = MagicMock()
        warmup_task.done.return_value = True

        def close_warmup_coroutine(coroutine):
            coroutine.close()
            return warmup_task

        with (
            patch.object(main, "settings", _settings()),
            patch.object(main, "postgres_database", database),
            patch.object(main, "create_application_repositories", return_value=MagicMock()),
            patch.object(main, "Redis", return_value=redis_client),
            patch.object(main.FastAPICache, "reset") as cache_reset,
            patch.object(main.asyncio, "create_task", side_effect=close_warmup_coroutine),
        ):
            async with main.lifespan(app):
                self.assertIsNone(app.state.redis)

            redis_client.aclose.assert_awaited_once_with()
            self.assertGreaterEqual(cache_reset.call_count, 2)
            database.close.assert_called_once_with()

    async def test_retries_redis_close_after_initial_cleanup_fails(self) -> None:
        app = FastAPI()
        database = MagicMock()
        redis_client = MagicMock()
        redis_client.ping = AsyncMock(side_effect=RuntimeError("redis unavailable"))
        redis_client.aclose = AsyncMock(
            side_effect=[RuntimeError("close unavailable"), None]
        )
        warmup_task = MagicMock()
        warmup_task.done.return_value = True

        def close_warmup_coroutine(coroutine):
            coroutine.close()
            return warmup_task

        with (
            patch.object(main, "settings", _settings()),
            patch.object(main, "postgres_database", database),
            patch.object(
                main,
                "create_application_repositories",
                return_value=MagicMock(),
            ),
            patch.object(main, "Redis", return_value=redis_client),
            patch.object(
                main.asyncio,
                "create_task",
                side_effect=close_warmup_coroutine,
            ),
        ):
            async with main.lifespan(app):
                self.assertIsNone(app.state.redis)

        self.assertEqual(redis_client.aclose.await_count, 2)
        database.close.assert_called_once_with()

    async def test_rolls_back_resources_when_scheduler_start_fails(self) -> None:
        app = FastAPI()
        database = MagicMock()
        repositories = MagicMock()
        rag_provider = MagicMock()
        scheduler_runtime = MagicMock()
        scheduler_runtime.start.side_effect = RuntimeError("scheduler failed")
        redis_client = MagicMock()
        redis_client.ping = AsyncMock()
        redis_client.keys = AsyncMock(return_value=[])
        redis_client.aclose = AsyncMock()
        warmup_task = MagicMock()
        warmup_task.done.return_value = True

        def close_warmup_coroutine(coroutine):
            coroutine.close()
            return warmup_task

        with (
            patch.object(main, "settings", _settings(scheduler_enabled=True)),
            patch.object(main, "postgres_database", database),
            patch.object(
                main,
                "create_application_repositories",
                return_value=repositories,
            ),
            patch.object(
                main,
                "RagChatServiceProvider",
                return_value=rag_provider,
            ),
            patch.object(
                main,
                "create_scheduler_runtime",
                return_value=scheduler_runtime,
            ),
            patch.object(main, "Redis", return_value=redis_client),
            patch.object(main.asyncio, "create_task", side_effect=close_warmup_coroutine),
        ):
            with self.assertRaisesRegex(RuntimeError, "scheduler failed"):
                async with main.lifespan(app):
                    pass

        scheduler_runtime.stop.assert_called_once_with()
        redis_client.aclose.assert_awaited_once_with()
        rag_provider.close.assert_called_once_with()
        database.close.assert_called_once_with()

    async def test_cleanup_failures_do_not_skip_remaining_resources(self) -> None:
        app = FastAPI()
        database = MagicMock()
        repositories = MagicMock()
        rag_provider = MagicMock()
        rag_provider.close.side_effect = RuntimeError("rag close failed")
        scheduler_runtime = MagicMock()
        scheduler_runtime.stop.side_effect = RuntimeError("scheduler close failed")
        redis_client = MagicMock()
        redis_client.ping = AsyncMock()
        redis_client.keys = AsyncMock(return_value=[])
        redis_client.aclose = AsyncMock(side_effect=RuntimeError("redis close failed"))
        warmup_task = MagicMock()
        warmup_task.done.return_value = True

        def close_warmup_coroutine(coroutine):
            coroutine.close()
            return warmup_task

        with (
            patch.object(main, "settings", _settings()),
            patch.object(main, "postgres_database", database),
            patch.object(
                main,
                "create_application_repositories",
                return_value=repositories,
            ),
            patch.object(
                main,
                "RagChatServiceProvider",
                return_value=rag_provider,
            ),
            patch.object(
                main,
                "create_scheduler_runtime",
                return_value=scheduler_runtime,
            ),
            patch.object(main, "Redis", return_value=redis_client),
            patch.object(main.asyncio, "create_task", side_effect=close_warmup_coroutine),
        ):
            async with main.lifespan(app):
                pass

        scheduler_runtime.stop.assert_called_once_with()
        redis_client.aclose.assert_awaited_once_with()
        rag_provider.close.assert_called_once_with()
        database.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
