"""X 视频封面端点契约测试。

接缝：x_poster_frames.get_upstream_client 注入 MockTransport；
x_poster_frames.poster_cache_dir 指向 tmp_path；routes_x_media 的
_extract_first_frame 别名用假实现替代真实 ffmpeg 子进程。
模块级负缓存/锁在 fixture 中清理，保证用例间隔离。
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_x_media
from backend.app.core.config import settings
from backend.app.services import x_poster_frames
from backend.tests.test_email_service_contracts import FakeRedis

VIDEO_URL = "https://video.twimg.com/amplify_video/123/vid/avc1/1920x1080/a.mp4?tag=29"
FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@pytest.fixture()
def poster_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """隔离模块态并返回装配器：handler=上游响应，extract=抽帧结果。"""

    # 特性开关默认关闭；海报路由用例一律在开启态下验证
    monkeypatch.setattr(settings, "x_source_enabled", True)
    routes_x_media._poster_locks.clear()
    routes_x_media._poster_negative.clear()
    monkeypatch.setattr(x_poster_frames, "poster_cache_dir", lambda: tmp_path)

    state = {"upstream_calls": 0, "extract_calls": 0, "extract_ok": True}

    def build(handler, *, with_redis: bool = True) -> TestClient:
        def fake_client_factory() -> httpx.AsyncClient:
            return httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                follow_redirects=False,
            )

        async def fake_extract(partial: bytes, out_path: Path) -> bool:
            state["extract_calls"] += 1
            if state["extract_ok"]:
                out_path.write_bytes(FAKE_JPEG)
                return True
            return False

        monkeypatch.setattr(x_poster_frames, "get_upstream_client", fake_client_factory)
        monkeypatch.setattr(routes_x_media, "_extract_first_frame", fake_extract)
        app = FastAPI()
        app.include_router(routes_x_media.router, prefix="/api")
        if with_redis:
            state["redis"] = FakeRedis()
            app.state.redis = state["redis"]
        return TestClient(app)

    def counting_handler(response: httpx.Response):
        def handler(request: httpx.Request) -> httpx.Response:
            state["upstream_calls"] += 1
            assert request.headers["range"].startswith("bytes=0-")
            return response

        return handler

    return state, build, counting_handler


class TestXMediaPoster:
    def test_generates_and_caches_poster(self, poster_env) -> None:
        state, build, counting_handler = poster_env
        client = build(counting_handler(httpx.Response(206, content=b"\x00" * 1024)))

        first = client.get("/api/media/x/poster", params={"url": VIDEO_URL})
        assert first.status_code == 200
        assert first.headers["Content-Type"] == "image/jpeg"
        assert first.content == FAKE_JPEG
        assert first.headers["Cache-Control"] == "public, max-age=604800"

        second = client.get("/api/media/x/poster", params={"url": VIDEO_URL})
        assert second.status_code == 200
        # 第二次命中磁盘缓存：不再回源、不再抽帧
        assert state["upstream_calls"] == 1
        assert state["extract_calls"] == 1

    def test_extract_failure_marks_negative_cache(self, poster_env) -> None:
        state, build, counting_handler = poster_env
        state["extract_ok"] = False
        client = build(counting_handler(httpx.Response(206, content=b"\x00" * 1024)))

        first = client.get("/api/media/x/poster", params={"url": VIDEO_URL})
        assert first.status_code == 404

        second = client.get("/api/media/x/poster", params={"url": VIDEO_URL})
        assert second.status_code == 404
        # 负缓存生效：第二次请求不再回源
        assert state["upstream_calls"] == 1
        # 失败后锁已释放，不泄漏
        assert routes_x_media._poster_locks == {}

    def test_upstream_404_marks_negative_cache(self, poster_env) -> None:
        state, build, counting_handler = poster_env
        client = build(counting_handler(httpx.Response(404, content=b"gone")))

        assert client.get("/api/media/x/poster", params={"url": VIDEO_URL}).status_code == 404
        assert client.get("/api/media/x/poster", params={"url": VIDEO_URL}).status_code == 404
        assert state["upstream_calls"] == 1
        assert state["extract_calls"] == 0

    def test_upstream_timeout_is_transient_504(self, poster_env) -> None:
        state, build, _ = poster_env

        def handler(request: httpx.Request) -> httpx.Response:
            state["upstream_calls"] += 1
            raise httpx.ConnectTimeout("boom", request=request)

        client = build(handler)
        assert client.get("/api/media/x/poster", params={"url": VIDEO_URL}).status_code == 504
        # 瞬态故障不记负缓存：下次仍会真实回源
        assert routes_x_media._poster_negative == {}

    def test_cache_hit_never_touches_upstream(self, poster_env, tmp_path: Path) -> None:
        state, build, _ = poster_env
        cache_path = routes_x_media._poster_cache_path(VIDEO_URL)
        cache_path.write_bytes(FAKE_JPEG)

        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("upstream must not be called on cache hit")

        client = build(handler)
        response = client.get("/api/media/x/poster", params={"url": VIDEO_URL})
        assert response.status_code == 200
        assert response.content == FAKE_JPEG
        assert state["extract_calls"] == 0

    def test_disallowed_host_rejected(self, poster_env) -> None:
        _, build, _ = poster_env

        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("upstream must not be called for disallowed hosts")

        client = build(handler)
        response = client.get(
            "/api/media/x/poster", params={"url": "https://evil.com/a.mp4"}
        )
        assert response.status_code == 403


class TestXMediaPosterRateLimit:
    """生成路径的匿名 IP 级限速：防无认证端点被用于 CPU/带宽放大。"""

    @staticmethod
    def _video_url(seed: int) -> str:
        return f"https://video.twimg.com/amplify_video/{seed}/vid/avc1/1920x1080/a.mp4"

    def test_generation_over_limit_returns_429_without_upstream(
        self, poster_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(routes_x_media, "_POSTER_GENERATE_RATE_LIMIT", 2)
        state, build, counting_handler = poster_env
        client = build(counting_handler(httpx.Response(206, content=b"\x00" * 1024)))

        for seed in (1, 2):
            response = client.get(
                "/api/media/x/poster", params={"url": self._video_url(seed)}
            )
            assert response.status_code == 200
        throttled = client.get(
            "/api/media/x/poster", params={"url": self._video_url(3)}
        )
        assert throttled.status_code == 429
        assert throttled.headers["Retry-After"] == "600"
        # 被限流的请求未触发回源/抽帧，锁无泄漏
        assert state["upstream_calls"] == 2
        assert state["extract_calls"] == 2
        assert routes_x_media._poster_locks == {}

    def test_spoofed_xff_does_not_split_quota(
        self, poster_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """不可信对端忽略 XFF：换头伪造来源 IP 不能拆分配额。"""
        monkeypatch.setattr(routes_x_media, "_POSTER_GENERATE_RATE_LIMIT", 1)
        state, build, counting_handler = poster_env
        client = build(counting_handler(httpx.Response(206, content=b"\x00" * 1024)))

        first = client.get(
            "/api/media/x/poster",
            params={"url": self._video_url(1)},
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        assert first.status_code == 200
        throttled = client.get(
            "/api/media/x/poster",
            params={"url": self._video_url(2)},
            headers={"X-Forwarded-For": "5.6.7.8"},
        )
        assert throttled.status_code == 429
        assert state["upstream_calls"] == 1

    def test_cache_hits_are_not_charged(
        self, poster_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """磁盘缓存命中不计费：正常浏览重复渲染不消耗生成配额。"""
        monkeypatch.setattr(routes_x_media, "_POSTER_GENERATE_RATE_LIMIT", 1)
        state, build, counting_handler = poster_env
        client = build(counting_handler(httpx.Response(206, content=b"\x00" * 1024)))

        first = client.get("/api/media/x/poster", params={"url": VIDEO_URL})
        assert first.status_code == 200
        for _ in range(5):
            cached = client.get("/api/media/x/poster", params={"url": VIDEO_URL})
            assert cached.status_code == 200
        assert state["upstream_calls"] == 1

    def test_negative_cache_hits_are_not_charged(
        self, poster_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(routes_x_media, "_POSTER_GENERATE_RATE_LIMIT", 1)
        state, build, counting_handler = poster_env
        client = build(counting_handler(httpx.Response(404, content=b"gone")))

        for _ in range(4):
            response = client.get("/api/media/x/poster", params={"url": VIDEO_URL})
            assert response.status_code == 404
        # 仅首次真实回源计费，负缓存期间的 404 不消耗配额、不被 429
        assert state["upstream_calls"] == 1

    def test_fail_open_when_redis_missing(
        self, poster_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(routes_x_media, "_POSTER_GENERATE_RATE_LIMIT", 1)
        state, build, counting_handler = poster_env
        client = build(
            counting_handler(httpx.Response(206, content=b"\x00" * 1024)),
            with_redis=False,
        )
        for seed in (1, 2):
            response = client.get(
                "/api/media/x/poster", params={"url": self._video_url(seed)}
            )
            assert response.status_code == 200
        assert state["upstream_calls"] == 2

    def test_fail_open_when_redis_broken(
        self, poster_env, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class BrokenRedis:
            async def incr(self, key: str) -> int:
                raise ConnectionError("redis down")

        monkeypatch.setattr(routes_x_media, "_POSTER_GENERATE_RATE_LIMIT", 1)
        state, build, counting_handler = poster_env
        client = build(counting_handler(httpx.Response(206, content=b"\x00" * 1024)))
        client.app.state.redis = BrokenRedis()

        for seed in (1, 2):
            response = client.get(
                "/api/media/x/poster", params={"url": self._video_url(seed)}
            )
            assert response.status_code == 200
        assert state["upstream_calls"] == 2
