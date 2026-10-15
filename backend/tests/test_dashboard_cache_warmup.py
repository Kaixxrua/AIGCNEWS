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


def _make_repositories(*, recent_docs_raiser: bool = False, dates: list[str] | None = None) -> SimpleNamespace:
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
        rank_snapshots=SimpleNamespace(get_snapshot_dates=lambda *args: dates or []),
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
        self.github_hot = SimpleNamespace(list_github_hot_dates=MagicMock(return_value=[]))
        self._reader_patch = patch(
            "backend.app.api.dashboard_cache_warmup.get_github_hot_board_reader",
            lambda: self.github_hot,
        )
        self._reader_patch.start()
        self.addCleanup(self._reader_patch.stop)
        self.addCleanup(FastAPICache.reset)

    async def test_warm_populates_frontend_initial_load_keys(self) -> None:
        await warm_dashboard_cache(_make_repositories())

        # static summary + 6 个源的 top 和日期清单；X recent 不参与缓存。
        self.assertEqual(len(_dashboard_keys()), 1 + 2 * len(_DASHBOARD_TAB_SOURCES))

    async def test_recent_history_and_x_request_shapes_hit_warmed_entries(self) -> None:
        today = datetime.now(_CST).date()
        history = [(today - timedelta(days=day)).isoformat() for day in range(1, 10)]
        dates = [today.isoformat(), *reversed(history), history[0]]
        repositories = _make_repositories(dates=dates)
        self.github_hot.list_github_hot_dates.return_value = dates
        await warm_dashboard_cache(repositories)
        before = _FakeQueryService.instances
        for source in _DASHBOARD_TAB_SOURCES:
            limit = 500 if source == "x" else 10
            for date in [None, *history[:7]]:
                query = f"limit={limit}&source={source}&period=daily&_board=visible-v1"
                if date:
                    query += f"&date={date}"
                await routes_dashboard.get_top_list(
                    request=_stub_request("/api/dashboard/top", query),
                    limit=limit, source=source, date=date,
                    rank_snapshots=repositories.rank_snapshots, github_hot=self.github_hot,
                )
        self.assertEqual(_FakeQueryService.instances, before)
        # 预热有界：更老日期仍按需读取，不把 90 天全量重新计算。
        await routes_dashboard.get_top_list(
            request=_stub_request("/api/dashboard/top", f"limit=10&source=github&date={history[7]}"),
            limit=10, source="github", date=history[7],
            rank_snapshots=repositories.rank_snapshots, github_hot=self.github_hot,
        )
        self.assertEqual(_FakeQueryService.instances, before + 1)
        self.github_hot.list_github_hot_dates.assert_called_once_with(limit=90)

    async def test_history_failure_does_not_prevent_other_sources_from_warming(self) -> None:
        dates = ["2020-01-02"]
        repositories = _make_repositories(dates=dates)
        self.github_hot.list_github_hot_dates.side_effect = RuntimeError("date lookup failed")
        await warm_dashboard_cache(repositories)
        before = _FakeQueryService.instances
        await routes_dashboard.get_top_list(
            request=_stub_request("/api/dashboard/top", "limit=10&source=news&date=2020-01-02"),
            limit=10, source="news", date=dates[0],
            rank_snapshots=repositories.rank_snapshots, github_hot=self.github_hot,
        )
        self.assertEqual(_FakeQueryService.instances, before)

    async def test_warmup_limits_concurrency_and_refreshes_history(self) -> None:
        active = peak = 0
        calls = []

        async def top(**kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            calls.append((kwargs["source"], kwargs["date"], kwargs["request"].headers.get("cache-control")))
            await asyncio.sleep(0)
            active -= 1
            return {}

        with patch("backend.app.api.dashboard_cache_warmup.get_top_list", side_effect=top):
            await warm_dashboard_cache(_make_repositories(dates=["2020-01-02"]), refresh=True)
        self.assertEqual(peak, 2)
        self.assertTrue(all(date is None for _, date, _ in calls[:6]))
        self.assertIn(("news", "2020-01-02", "no-cache"), calls)

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
        self.assertEqual(_next_warmup_delay(datetime(2026, 9, 11, 12, tzinfo=_CST)), 45)
        self.assertEqual(_next_warmup_delay(datetime(2026, 9, 11, 23, 59, 58, tzinfo=_CST)), 3)

    async def test_single_endpoint_failure_does_not_break_others(self) -> None:
        # 动态 X recent 不参与预热；即使 documents 查询故障，也不影响
        # summary 与 6 个 top 的静态首屏缓存。
        await warm_dashboard_cache(_make_repositories(recent_docs_raiser=True))

        self.assertEqual(len(_dashboard_keys()), 1 + 2 * len(_DASHBOARD_TAB_SOURCES))

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
