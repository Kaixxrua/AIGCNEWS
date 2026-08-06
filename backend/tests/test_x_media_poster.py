"""X 视频封面端点契约测试。

接缝：_get_upstream_client 注入 MockTransport；_poster_cache_dir 指向
tmp_path；_extract_first_frame 用假实现替代真实 ffmpeg 子进程。
模块级负缓存/锁在 fixture 中清理，保证用例间隔离。
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api import routes_x_media

VIDEO_URL = "https://video.twimg.com/amplify_video/123/vid/avc1/1920x1080/a.mp4?tag=29"
FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


@pytest.fixture()
def poster_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """隔离模块态并返回装配器：handler=上游响应，extract=抽帧结果。"""

    routes_x_media._poster_locks.clear()
    routes_x_media._poster_negative.clear()
    monkeypatch.setattr(routes_x_media, "_poster_cache_dir", lambda: tmp_path)

    state = {"upstream_calls": 0, "extract_calls": 0, "extract_ok": True}

    def build(handler) -> TestClient:
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

        monkeypatch.setattr(routes_x_media, "_get_upstream_client", fake_client_factory)
        monkeypatch.setattr(routes_x_media, "_extract_first_frame", fake_extract)
        app = FastAPI()
        app.include_router(routes_x_media.router, prefix="/api")
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
