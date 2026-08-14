from __future__ import annotations

"""x_media_warmup 服务测试：MockTransport 注入 _get_warmup_client 测试缝，
验证预热请求集合、计数、并发上限与开关门。async 用例一律
IsolatedAsyncioTestCase（项目约定）。
"""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

# 提前导入子模块：patch 目标经 getattr 链解析，包未导入子模块时
# patch("...ingestion.cache_invalidation....") 会 AttributeError
import backend.app.services.ingestion.cache_invalidation  # noqa: F401
from backend.app.core.config import settings
from backend.app.services import x_media_warmup
from backend.app.services.x_media_warmup import (
    _EMPTY_RESULT,
    spawn_x_media_warmup_task,
    warm_recent_x_media,
)


def _fake_documents(docs: list[dict]) -> SimpleNamespace:
    calls: list[dict] = []

    def list_recent_by_source(source, *, since_iso, until_iso=None, limit=500):
        calls.append(
            {"source": source, "since_iso": since_iso, "until_iso": until_iso, "limit": limit}
        )
        return docs

    return SimpleNamespace(list_recent_by_source=list_recent_by_source, calls=calls)


_PHOTO_DOC = {
    "author_avatar_url": "https://pbs.twimg.com/profile_images/1/a_normal.jpg",
    "media": [
        {"type": "photo", "url": "https://pbs.twimg.com/media/a.jpg"},
        {
            "type": "video",
            "url": "https://video.twimg.com/v.mp4",
            "poster_url": "https://pbs.twimg.com/amplify_video_thumb/1/img/x.jpg",
        },
    ],
}

_EXPECTED_PATHS = [
    "/api/media/x/img/pbs.twimg.com/profile_images/1/a_normal.jpg",
    "/api/media/x/img/pbs.twimg.com/media/a.jpg?name=small",
    "/api/media/x/img/pbs.twimg.com/amplify_video_thumb/1/img/x.jpg?name=small",
]


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class WarmRecentXMediaTest(unittest.IsolatedAsyncioTestCase):
    async def test_empty_base_url_skips_without_querying_repo(self) -> None:
        documents = _fake_documents([_PHOTO_DOC])
        result = await warm_recent_x_media(documents, base_url="")
        self.assertEqual(result, _EMPTY_RESULT)
        self.assertEqual(documents.calls, [])

    async def test_warms_exact_frontend_paths(self) -> None:
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            return httpx.Response(200, content=b"x")

        documents = _fake_documents([_PHOTO_DOC])
        with patch.object(
            x_media_warmup, "_get_warmup_client", lambda: _mock_client(handler)
        ):
            result = await warm_recent_x_media(
                documents, base_url="http://127.0.0.1:8488/"
            )
        self.assertEqual(
            sorted(requested),
            sorted(f"http://127.0.0.1:8488{path}" for path in _EXPECTED_PATHS),
        )
        self.assertEqual(result.docs_scanned, 1)
        self.assertEqual(result.urls_collected, len(_EXPECTED_PATHS))
        self.assertEqual(result.ok, len(_EXPECTED_PATHS))
        self.assertEqual(result.failed, 0)

    async def test_mixed_outcomes_counted_without_raising(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if "profile_images" in request.url.path:
                return httpx.Response(404)  # twimg 死链
            if "media/a.jpg" in request.url.path:
                raise httpx.ConnectError("boom", request=request)
            return httpx.Response(200, content=b"x")

        documents = _fake_documents([_PHOTO_DOC])
        with patch.object(
            x_media_warmup, "_get_warmup_client", lambda: _mock_client(handler)
        ):
            result = await warm_recent_x_media(documents, base_url="http://edge")
        self.assertEqual(result.ok, 1)
        self.assertEqual(result.failed, 2)

    async def test_concurrency_bound_respected(self) -> None:
        in_flight = 0
        max_in_flight = 0

        async def slow_handler(request: httpx.Request) -> httpx.Response:
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            return httpx.Response(200, content=b"x")

        docs = [
            {"media": [{"type": "photo", "url": f"https://pbs.twimg.com/media/{i}.jpg"}]}
            for i in range(10)
        ]
        documents = _fake_documents(docs)

        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("async handler 应走 transport 异步路径")

        async def dispatch(request: httpx.Request) -> httpx.Response:
            return await slow_handler(request)

        with patch.object(
            x_media_warmup,
            "_get_warmup_client",
            lambda: httpx.AsyncClient(
                transport=httpx.MockTransport(dispatch)  # 支持 async handler
            ),
        ):
            result = await warm_recent_x_media(
                documents, base_url="http://edge", concurrency=3
            )
        self.assertEqual(result.ok, 10)
        self.assertLessEqual(max_in_flight, 3)

    async def test_max_urls_truncates_requests(self) -> None:
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            return httpx.Response(200, content=b"x")

        documents = _fake_documents([_PHOTO_DOC])
        with patch.object(
            x_media_warmup, "_get_warmup_client", lambda: _mock_client(handler)
        ):
            result = await warm_recent_x_media(
                documents, base_url="http://edge", max_urls=1
            )
        self.assertEqual(len(requested), 1)
        self.assertEqual(result.urls_collected, 1)

    async def test_no_media_docs_short_circuits(self) -> None:
        documents = _fake_documents([{"summary": "纯文本推文"}])
        result = await warm_recent_x_media(documents, base_url="http://edge")
        self.assertEqual(result.urls_collected, 0)
        self.assertEqual(result.attempted, 0)

    async def test_warmup_client_ignores_env_proxy(self) -> None:
        # trust_env=False 是承重墙：宿主机 HTTPS_PROXY 指向 twimg socks 链路，
        # localhost 边缘预热绝不能被 env 拐进代理
        x_media_warmup._warmup_client = None
        try:
            with patch.dict(
                "os.environ", {"HTTPS_PROXY": "socks5://10.0.0.1:1080"}
            ):
                client = x_media_warmup._get_warmup_client()
            self.assertFalse(client.trust_env)
        finally:
            x_media_warmup._warmup_client = None


class SpawnWarmupTaskTest(unittest.IsolatedAsyncioTestCase):
    async def test_switches_off_returns_none(self) -> None:
        documents = _fake_documents([])
        with (
            patch.object(settings, "x_media_warmup_enabled", False),
            patch.object(settings, "x_source_enabled", True),
        ):
            self.assertIsNone(spawn_x_media_warmup_task(documents))
        with (
            patch.object(settings, "x_media_warmup_enabled", True),
            patch.object(settings, "x_source_enabled", False),
        ):
            self.assertIsNone(spawn_x_media_warmup_task(documents))

    async def test_spawn_runs_warmup_and_is_tracked(self) -> None:
        documents = _fake_documents([])
        with (
            patch.object(settings, "x_media_warmup_enabled", True),
            patch.object(settings, "x_source_enabled", True),
            patch.object(
                x_media_warmup, "warm_recent_x_media", return_value=_EMPTY_RESULT
            ) as warm,
        ):
            task = spawn_x_media_warmup_task(documents)
            self.assertIsNotNone(task)
            assert task is not None
            self.assertIn(task, x_media_warmup._WARMUP_TASKS)
            await task
            warm.assert_awaited_once_with(documents)
            self.assertNotIn(task, x_media_warmup._WARMUP_TASKS)

    async def test_warmup_exception_does_not_escape_task(self) -> None:
        documents = _fake_documents([])
        with (
            patch.object(settings, "x_media_warmup_enabled", True),
            patch.object(settings, "x_source_enabled", True),
            patch.object(
                x_media_warmup,
                "warm_recent_x_media",
                side_effect=RuntimeError("预热炸了"),
            ),
        ):
            task = spawn_x_media_warmup_task(documents)
            assert task is not None
            await task  # 不抛即通过：detached 旁路异常必须就地吞掉
            self.assertTrue(task.done())


class CompositionWiringTest(unittest.IsolatedAsyncioTestCase):
    """采集后钩子接线：cache_invalidator 须触发一次媒体预热 spawn。

    spawn 是 fire-and-forget（不拖慢采集主流程），断言「被调用且未被 await」
    即可；Redis 清理与 dashboard 预热路径由 test_dashboard_cache_warmup.py 覆盖。
    """

    async def test_cache_invalidator_spawns_media_warmup_once(self) -> None:
        from backend.app.services.ingestion.composition import (
            provide_ingestion_dependencies,
        )

        documents = _fake_documents([])
        repositories = SimpleNamespace(documents=documents)
        spawn_calls: list[object] = []

        def fake_spawn(docs: object) -> None:
            spawn_calls.append(docs)
            return None

        with (
            patch.object(settings, "x_source_enabled", False),
            patch(
                "backend.app.services.ingestion.cache_invalidation"
                ".clear_dashboard_cache_safely",
                new=AsyncMock(),
            ),
            patch(
                "backend.app.api.dashboard_cache_warmup.warm_dashboard_cache",
                new=AsyncMock(),
            ),
            patch(
                "backend.app.services.x_media_warmup.spawn_x_media_warmup_task",
                side_effect=fake_spawn,
            ),
        ):
            dependencies = provide_ingestion_dependencies(
                repositories=repositories, task_writer=object()
            )
            await dependencies.cache_invalidator()

        self.assertEqual(spawn_calls, [documents])
