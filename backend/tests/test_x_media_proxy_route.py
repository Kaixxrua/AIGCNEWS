"""X 媒体代理路由契约测试。

monkeypatch _get_upstream_client 注入 MockTransport，走真实 httpx 管线验证：
URL 白名单（SSRF 边界）、Range 透传、状态码语义、流式回包。
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app.api import routes_x_media
from backend.app.api.routes_x_media import validate_media_url

PHOTO_URL = "https://pbs.twimg.com/media/HO0uUesbYAAaHzK.jpg"
VIDEO_URL = "https://video.twimg.com/amplify_video/123/vid/avc1/1920x1080/a.mp4?tag=29"


@pytest.fixture()
def build_client(monkeypatch: pytest.MonkeyPatch):
    """返回一个工厂：以 MockTransport handler 替换上游客户端，挂真实 FastAPI 路由。"""

    def build(handler) -> TestClient:
        def fake_client_factory() -> httpx.AsyncClient:
            return httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                follow_redirects=False,
            )

        monkeypatch.setattr(routes_x_media, "_get_upstream_client", fake_client_factory)
        app = FastAPI()
        app.include_router(routes_x_media.router, prefix="/api")
        return TestClient(app)

    return build


class TestValidateMediaUrl:
    @pytest.mark.parametrize(
        "url", [PHOTO_URL, VIDEO_URL, "https://abs.twimg.com/hash.png"]
    )
    def test_accepts_twimg_https(self, url: str) -> None:
        assert validate_media_url(url) == url

    @pytest.mark.parametrize(
        "url",
        [
            "http://pbs.twimg.com/x.jpg",  # 非 https
            "https://evil.com/x.jpg",  # 白名单外主机
            "https://pbs.twimg.com.evil.com/x.jpg",  # 后缀欺骗
            "https://pbs.twimg.com./x.jpg",  # trailing dot
            "https://user:pass@pbs.twimg.com/x.jpg",  # userinfo
            "https://pbs.twimg.com:8443/x.jpg",  # 非标端口
            "https://pbs.twimg.com:abc/x.jpg",  # 非法端口
            "not-a-url",
        ],
    )
    def test_rejects_ssrf_variants(self, url: str) -> None:
        with pytest.raises(HTTPException) as exc_info:
            validate_media_url(url)
        assert exc_info.value.status_code in (400, 403)


class TestProxyXMedia:
    def test_streams_photo_with_cache_headers(self, build_client) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.host == "pbs.twimg.com"
            return httpx.Response(
                200,
                content=b"\xff\xd8\xffjpeg-bytes",
                headers={"Content-Type": "image/jpeg", "ETag": '"abc"'},
            )

        response = build_client(handler).get(
            "/api/media/x/proxy", params={"url": PHOTO_URL}
        )

        assert response.status_code == 200
        assert response.content == b"\xff\xd8\xffjpeg-bytes"
        assert response.headers["Content-Type"] == "image/jpeg"
        assert response.headers["ETag"] == '"abc"'
        assert response.headers["Cache-Control"] == "public, max-age=86400"

    def test_forwards_range_and_returns_206(self, build_client) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["range"] == "bytes=0-1023"
            return httpx.Response(
                206,
                content=b"\x00" * 1024,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Range": "bytes 0-1023/8355107",
                    "Accept-Ranges": "bytes",
                    "Content-Length": "1024",
                },
            )

        response = build_client(handler).get(
            "/api/media/x/proxy",
            params={"url": VIDEO_URL},
            headers={"Range": "bytes=0-1023"},
        )

        assert response.status_code == 206
        assert response.headers["Content-Range"] == "bytes 0-1023/8355107"
        assert response.headers["Accept-Ranges"] == "bytes"

    def test_upstream_404_passthrough(self, build_client) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, content=b"not found")

        response = build_client(handler).get(
            "/api/media/x/proxy", params={"url": VIDEO_URL}
        )
        assert response.status_code == 404

    def test_upstream_redirect_rejected_as_502(self, build_client) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": "https://evil.com/x.mp4"})

        response = build_client(handler).get(
            "/api/media/x/proxy", params={"url": VIDEO_URL}
        )
        assert response.status_code == 502

    def test_upstream_timeout_maps_to_504(self, build_client) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("boom", request=request)

        response = build_client(handler).get(
            "/api/media/x/proxy", params={"url": VIDEO_URL}
        )
        assert response.status_code == 504

    def test_disallowed_host_never_touches_upstream(self, build_client) -> None:
        def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
            raise AssertionError("upstream must not be called for disallowed hosts")

        response = build_client(handler).get(
            "/api/media/x/proxy", params={"url": "https://evil.com/x.mp4"}
        )
        assert response.status_code == 403
