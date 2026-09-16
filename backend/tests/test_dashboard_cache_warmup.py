from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

from backend.app.api import routes_dashboard
from backend.app.api.dashboard_cache_warmup import (
    _DASHBOARD_TAB_SOURCES,
    _next_warmup_delay,
    _stub_request,
    maintain_dashboard_cache,
    warm_dashboard_cache,
)

_CST = timezone(timedelta(hours=8))


def _today() -> str:
    return datetime.now(_CST).strftime("%Y-%m-%d")


class _FakeQueryService:
    """替代 DashboardQueryService：记录实例化次数，返回空文档集。

    预热只关心「cache key 是否被正确写入/命中」，不验证榜单内容；
    实例化计数用于判定后续请求是否走了缓存（命中则不再实例化）。
    """

    instances = 0

    def __init__(self, rank_snapshots, github_hot=None) -> None:
        type(self).instances += 1

    @classmethod
    def reset(cls) -> None:
        cls.instances = 0

    def resolve_display_snapshot_date(self, date, period, source_type):
        return {
            "requested_date": date,
            "resolved_date": date or _today(),
            "stale": False,
        }

    def get_docs_for_date(self, date_str, period, source_type=None, limit=500):
        return []


def _make_repositories(*, recent_docs_raiser: bool = False) -> SimpleNamespace:
    def _list_recent(source, since_iso, limit, until_iso=None, keyset_after=None):
        if recent_docs_raiser:
            raise RuntimeError("documents 查询故障")
        return []

    documents = SimpleNamespace(
        get_source_counts=lambda: {},
        get_today_document_count=lambda: 0,
        list_recent_by_source=_list_recent,
    )
    users = SimpleNamespace(
        get_user_count=lambda: 1,
        get_today_registered_user_count=lambda: 0,
    )
    return SimpleNamespace(
        users=users,
        documents=documents,
        rank_snapshots=object(),
    )


def _dashboard_keys() -> set[str]:
    return {k for k in InMemoryBackend._store if ":dashboard:" in k}


class WarmDashboardCacheTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        InMemoryBackend._store.clear()
        FastAPICache.reset()
        FastAPICache.init(InMemoryBackend(), prefix="aigc-cache:")
        _FakeQueryService.reset()
        self._qs_patch = patch.object(
            routes_dashboard, "DashboardQueryService", _FakeQueryService
        )
        self._qs_patch.start()
        self.addCleanup(self._qs_patch.stop)
        self._reader_patch = patch(
            "backend.app.api.dashboard_cache_warmup.get_github_hot_board_reader",
            lambda: None,
        )
        self._reader_patch.start()
        self.addCleanup(self._reader_patch.stop)
        self.addCleanup(FastAPICache.reset)

    async def test_warm_populates_frontend_initial_load_keys(self) -> None:
        await warm_dashboard_cache(_make_repositories())

        # static summary + 6 个源 tab 的 top；X recent 是动态无缓存查询
        self.assertEqual(len(_dashboard_keys()), 1 + len(_DASHBOARD_TAB_SOURCES))

    async def test_frontend_request_shape_hits_warmed_cache(self) -> None:
        repositories = _make_repositories()
        await warm_dashboard_cache(repositories)
        instances_after_warm = _FakeQueryService.instances
        self.assertGreater(instances_after_warm, 0)

        # 模拟当前前端首屏真实请求：当天不传日期，允许回溯最近快照。
        # 命中预热缓存则不会再实例化查询服务
        result = await routes_dashboard.get_top_list(
            request=_stub_request(
                "/api/dashboard/top",
                "limit=10&source=github&period=daily",
            ),
            limit=10,
            source="github",
            date=None,
            rank_snapshots=repositories.rank_snapshots,
            github_hot=None,
        )
        self.assertEqual(_FakeQueryService.instances, instances_after_warm)
        self.assertIn("items", result)
        self.assertFalse(result["is_embargoed"] and result["items"] is None)

    async def test_warmup_uses_static_summary_without_dynamic_counters(self) -> None:
        repositories = _make_repositories()
        await warm_dashboard_cache(repositories)
        instances_after_warm = _FakeQueryService.instances

        result = await routes_dashboard.get_dashboard_summary_static(
            date=None,
            rank_snapshots=repositories.rank_snapshots,
            github_hot=None,
            __fastapi_cache_request=_stub_request(
                "/api/dashboard/summary-static", "period=daily"
            ),
        )

        self.assertNotIn("stats", result)
        self.assertIn("top_list", result)
        self.assertIn("radar", result)
        self.assertEqual(_FakeQueryService.instances, instances_after_warm)

    async def test_explicit_today_keeps_a_separate_exact_date_cache(self) -> None:
        repositories = _make_repositories()
        await warm_dashboard_cache(repositories)
        before = _FakeQueryService.instances
        await routes_dashboard.get_top_list(
            request=_stub_request("/api/dashboard/top", f"limit=10&source=github&date={_today()}"),
            limit=10, source="github", date=_today(),
            rank_snapshots=repositories.rank_snapshots, github_hot=None,
        )
        self.assertEqual(_FakeQueryService.instances, before + 1)

    async def test_refresh_replaces_warm_entries_before_their_expiry(self) -> None:
        repositories = _make_repositories()
        await warm_dashboard_cache(repositories)
        before = _FakeQueryService.instances
        keys = _dashboard_keys()
        await warm_dashboard_cache(repositories, refresh=True)
        self.assertEqual(_FakeQueryService.instances, before * 2)
        self.assertEqual(_dashboard_keys(), keys)

    async def test_maintenance_warms_at_startup_and_retries_after_failure(self) -> None:
        repositories = _make_repositories()
        with (
            patch("backend.app.api.dashboard_cache_warmup.warm_dashboard_cache",
                  new=AsyncMock(side_effect=[RuntimeError("temporary"), None])) as warm,
            patch("backend.app.api.dashboard_cache_warmup.asyncio.sleep",
                  new=AsyncMock(side_effect=[None, asyncio.CancelledError])) as sleep,
        ):
            with self.assertRaises(asyncio.CancelledError):
                await maintain_dashboard_cache(repositories)
        self.assertEqual(warm.await_count, 2)
        warm.assert_awaited_with(repositories, refresh=True)
        self.assertTrue(all(0 < call.args[0] <= 1800 for call in sleep.await_args_list))

    def test_next_refresh_is_before_expiry_and_just_after_midnight(self) -> None:
        self.assertEqual(_next_warmup_delay(datetime(2026, 9, 11, 12, tzinfo=_CST)), 1800)
        self.assertEqual(_next_warmup_delay(datetime(2026, 9, 11, 23, 59, 58, tzinfo=_CST)), 3)

    async def test_single_endpoint_failure_does_not_break_others(self) -> None:
        # 动态 X recent 不参与预热；即使 documents 查询故障，也不影响
        # summary 与 6 个 top 的静态首屏缓存。
        await warm_dashboard_cache(_make_repositories(recent_docs_raiser=True))

        self.assertEqual(len(_dashboard_keys()), 1 + len(_DASHBOARD_TAB_SOURCES))

    async def test_invalidator_composition_clears_then_warms(self) -> None:
        from backend.app.services.ingestion.composition import (
            provide_ingestion_dependencies,
        )

        repositories = _make_repositories()
        clear_mock = AsyncMock()
        warm_mock = AsyncMock()
        with patch(
            "backend.app.services.ingestion.cache_invalidation.clear_dashboard_cache_safely",
            clear_mock,
        ), patch(
            "backend.app.api.dashboard_cache_warmup.warm_dashboard_cache",
            warm_mock,
        ):
            dependencies = provide_ingestion_dependencies(
                repositories=repositories,
                task_writer=MagicMock(),
            )
            await dependencies.cache_invalidator()

        clear_mock.assert_awaited_once()
        warm_mock.assert_awaited_once_with(repositories)


if __name__ == "__main__":
    unittest.main()
