"""微信图片代理路由契约测试。

monkeypatch _get_upstream_client 注入 MockTransport、_cache_dir 指向
tmp_path，走真实 httpx 管线验证：URL 白名单（SSRF 边界）、Referer
防盗链头、图片磁盘缓存、负缓存与状态码语义。
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.app.api import routes_wechat_media
from backend.app.api.routes_wechat_media import validate_wechat_media_url

IMAGE_URL = "https://mmbiz.qpic.cn/mmbiz_png/abc/640?wx_fmt=png&from=appmsg"
LOGO_URL = "https://mmbiz.qlogo.cn/mmbiz/xyz/0"


@pytest.fixture()
def build_client(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """返回一个工厂：以 MockTransport handler 替换上游客户端，挂真实 FastAPI 路由。"""

    def build(handler, redis=None) -> TestClient:
        def fake_client_factory() -> httpx.AsyncClient:
            return httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
                follow_redirects=False,
            )

        from backend.app.core.config import settings

        monkeypatch.setattr(settings, "wechat_source_enabled", True)
        monkeypatch.setattr(routes_wechat_media, "_get_upstream_client", fake_client_factory)
        monkeypatch.setattr(routes_wechat_media, "_cache_dir", lambda: tmp_path)
        monkeypatch.setattr(routes_wechat_media, "_negative_cache", {})
        app = FastAPI()
        app.include_router(routes_wechat_media.router, prefix="/api")
        app.state.redis = redis  # None = 未配置 → 限速 fail-open（既有用例口径）
        return TestClient(app)

    return build


class TestValidateWeChatMediaUrl:
    @pytest.mark.parametrize("url", [IMAGE_URL, LOGO_URL])
    def test_accepts_mmbiz_https(self, url: str) -> None:
        assert validate_wechat_media_url(url) == url

    @pytest.mark.parametrize(
        "url",
        [
            "http://mmbiz.qpic.cn/x.jpg",  # 非 https
            "https://evil.com/x.jpg",  # 白名单外主机
            "https://mmbiz.qpic.cn.evil.com/x.jpg",  # 后缀欺骗
            "https://mmbiz.qpic.cn./x.jpg",  # trailing dot
            "https://user:pass@mmbiz.qpic.cn/x.jpg",  # userinfo
            "https://mmbiz.qpic.cn:8443/x.jpg",  # 非标端口
            "https://mmbiz.qpic.cn:abc/x.jpg",  # 非法端口
            "not-a-url",
        ],
    )
    def test_rejects_ssrf_variants(self, url: str) -> None:
        with pytest.raises(HTTPException) as exc_info:
            validate_wechat_media_url(url)
        assert exc_info.value.status_code in (400, 403)


class TestProxyWeChatMedia:
    def test_serves_image_with_referer_and_caches_to_disk(self, build_client, tmp_path) -> None:
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(
                200,
                headers={"content-type": "image/png"},
                content=b"\x89PNG-fake-bytes",
            )

        client = build_client(handler)
        response = client.get("/api/media/wechat/proxy", params={"url": IMAGE_URL})

        assert response.status_code == 200
        assert response.content == b"\x89PNG-fake-bytes"
        assert response.headers["Cache-Control"] == "public, max-age=86400"
        # 防盗链：上游请求必须携带 mp 域 Referer
        assert calls[0].headers["Referer"] == "https://mp.weixin.qq.com/"
        # 落盘缓存：wx_fmt=png 推断后缀
        assert (tmp_path / "f2de8a94234497a0e96079d6106f21e9.png").exists() or any(
            p.suffix == ".png" for p in tmp_path.iterdir()
        )

        # 第二次请求命中缓存，零上游调用
        response2 = client.get("/api/media/wechat/proxy", params={"url": IMAGE_URL})
        assert response2.status_code == 200
        assert response2.content == b"\x89PNG-fake-bytes"
        assert len(calls) == 1

    def test_upstream_404_negative_cached(self, build_client) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(404)

        client = build_client(handler)
        assert client.get("/api/media/wechat/proxy", params={"url": IMAGE_URL}).status_code == 404
        assert client.get("/api/media/wechat/proxy", params={"url": IMAGE_URL}).status_code == 404
        assert calls == 1  # 负缓存生效

    def test_upstream_redirect_rejected_as_502(self, build_client) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"location": "https://evil.com/x.png"})

        client = build_client(handler)
        response = client.get("/api/media/wechat/proxy", params={"url": IMAGE_URL})
        assert response.status_code == 502

    def test_non_image_content_type_rejected(self, build_client) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                content=b"<html>antispider</html>",
            )

        client = build_client(handler)
        response = client.get("/api/media/wechat/proxy", params={"url": IMAGE_URL})
        assert response.status_code == 502

    def test_upstream_timeout_maps_to_504(self, build_client) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("boom")

        client = build_client(handler)
        response = client.get("/api/media/wechat/proxy", params={"url": IMAGE_URL})
        assert response.status_code == 504

    def test_disallowed_host_never_touches_upstream(self, build_client) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("upstream must not be touched")

        client = build_client(handler)
        response = client.get(
            "/api/media/wechat/proxy", params={"url": "https://evil.com/x.png"}
        )
        assert response.status_code == 403

    def test_proxy_404_when_wechat_source_disabled(self, build_client, monkeypatch) -> None:
        from backend.app.core.config import settings

        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("disabled source must not touch upstream")

        client = build_client(handler)
        monkeypatch.setattr(settings, "wechat_source_enabled", False)
        response = client.get("/api/media/wechat/proxy", params={"url": IMAGE_URL})
        assert response.status_code == 404
        assert response.json()["detail"] == "wechat_source_disabled"


class TestProxyWeChatMediaRateLimit:
    """回源 miss 路径的匿名 IP 级限速（30 次/10 分钟，对齐 routes_x_media）。"""

    def _image_handler(self, calls: list[httpx.Request]):
        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(
                200,
                headers={"content-type": "image/png"},
                content=b"\x89PNG-fake-bytes",
            )

        return handler

    def test_miss_path_rate_limited_after_30_fetches(self, build_client) -> None:
        from backend.tests.test_email_service_contracts import FakeRedis

        calls: list[httpx.Request] = []
        client = build_client(self._image_handler(calls), redis=FakeRedis())

        # 每次换 URL 强制走 miss 回源路径（缓存命中不计费）
        for index in range(30):
            response = client.get(
                "/api/media/wechat/proxy",
                params={"url": f"{IMAGE_URL}&miss={index}"},
            )
            assert response.status_code == 200, f"fetch {index + 1}"
        assert len(calls) == 30

        response = client.get(
            "/api/media/wechat/proxy",
            params={"url": f"{IMAGE_URL}&miss=31"},
        )
        assert response.status_code == 429
        assert response.headers["Retry-After"] == "600"
        assert len(calls) == 30  # 限流后不再回源

    def test_cache_hits_are_not_billed(self, build_client) -> None:
        from backend.tests.test_email_service_contracts import FakeRedis

        calls: list[httpx.Request] = []
        client = build_client(self._image_handler(calls), redis=FakeRedis())

        # 同一 URL 重复渲染：首次 miss 计 1 次，其余全部命中磁盘缓存
        for _ in range(35):
            response = client.get("/api/media/wechat/proxy", params={"url": IMAGE_URL})
            assert response.status_code == 200
        assert len(calls) == 1
