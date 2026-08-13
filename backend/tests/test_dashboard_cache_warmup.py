from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi_cache import FastAPICache
from fastapi_cache.backends.inmemory import InMemoryBackend

from backend.app.api import routes_dashboard
from backend.app.api.dashboard_cache_warmup import (
    _DASHBOARD_TAB_SOURCES,
    _stub_request,
    warm_dashboard_cache,
)
from backend.app.repositories.site_visit_repository import SiteVisitStats

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
    def _list_recent(source, since_iso, limit, until_iso=None):
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
        catalog = SimpleNamespace(github_library_total=AsyncMock(return_value=0))
        self._catalog_patch = patch(
            "backend.app.api.dashboard_cache_warmup.get_project_catalog_query_service",
            lambda: catalog,
        )
        self._catalog_patch.start()
        self.addCleanup(self._catalog_patch.stop)
        # 预热直调不走 FastAPI DI，仓储按依赖函数解析；假实现返回固定计数，
        # 用于断言预热写入的 summary 缓存携带真实访客数而非 0。
        self._visits = MagicMock()
        self._visits.get_visit_stats.return_value = SiteVisitStats(
            today_visits=7, total_visits=700
        )
        self._visits_patch = patch(
            "backend.app.api.dashboard_cache_warmup.get_site_visit_repository",
            lambda: self._visits,
        )
        self._visits_patch.start()
        self.addCleanup(self._visits_patch.stop)
        self.addCleanup(FastAPICache.reset)

    async def test_warm_populates_frontend_initial_load_keys(self) -> None:
        await warm_dashboard_cache(_make_repositories())

        # summary + 6 个源 tab 的 top + x/recent，共 8 个 key
        self.assertEqual(len(_dashboard_keys()), 1 + len(_DASHBOARD_TAB_SOURCES) + 1)

    async def test_frontend_request_shape_hits_warmed_cache(self) -> None:
        repositories = _make_repositories()
        await warm_dashboard_cache(repositories)
        instances_after_warm = _FakeQueryService.instances
        self.assertGreater(instances_after_warm, 0)

        # 模拟前端首屏真实请求（useDashboardData: tab=github, limit=10, date=今天）
        # 命中预热缓存则不会再实例化查询服务
        today = _today()
        result = await routes_dashboard.get_top_list(
            request=_stub_request(
                "/api/dashboard/top",
                f"limit=10&source=github&period=daily&date={today}",
            ),
            limit=10,
            source="github",
            date=today,
            rank_snapshots=repositories.rank_snapshots,
            github_hot=None,
        )
        self.assertEqual(_FakeQueryService.instances, instances_after_warm)
        self.assertIn("items", result)
        self.assertFalse(result["is_embargoed"] and result["items"] is None)

    async def test_warmed_summary_carries_real_visit_counts(self) -> None:
        """回归：预热直调必须显式传 visits 仓储。

        漏传时端点拿到 Depends 默认值，AttributeError 被宽捕获吞成 0 并写进
        3600s summary 缓存——2026-08-13 生产看板访客数间歇为 0 的根因。
        """
        repositories = _make_repositories()
        await warm_dashboard_cache(repositories)

        today = _today()
        result = await routes_dashboard.get_dashboard_summary(
            request=_stub_request(
                "/api/dashboard/summary", f"period=daily&date={today}"
            ),
            date=today,
            user_statistics=repositories.users,
            document_statistics=repositories.documents,
            rank_snapshots=repositories.rank_snapshots,
            catalog=MagicMock(),
            github_hot=None,
            visits=MagicMock(),  # 命中缓存则不会执行函数体，传什么都不会被读
        )

        self.assertEqual(result["stats"]["today_visits"], 7)
        self.assertEqual(result["stats"]["total_visits"], 700)
        # 仅预热时查过一次计数库：二次调用命中缓存，未再执行端点体
        self.assertEqual(self._visits.get_visit_stats.call_count, 1)

    async def test_single_endpoint_failure_does_not_break_others(self) -> None:
        # x/recent 依赖的 documents 查询抛错：该端点预热失败，
        # 但 summary 与 6 个 top 仍应写入缓存，且整体不向外抛异常
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
