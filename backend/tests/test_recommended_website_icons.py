"""Curated website icons: fetched through the pinned tool website fetcher, stored only as re-encoded WebP."""

from __future__ import annotations

import io
import re
from unittest.mock import Mock

import httpx
import pytest
from PIL import Image

from backend.app.core.config import settings
from backend.app.services import outbound_target_policy, recommended_website_icons
from backend.app.services.ingestion import tool_website_fetcher

PUBLIC_IP = "93.184.216.34"
PAGE = b"""<html><head><title>Example</title><link rel="apple-touch-icon" href="/touch.png"></head>
<body><main><p>Example tools for everyone.</p></main></body></html>"""
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8"><rect width="8" height="8" fill="red"/></svg>'


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGBA", (96, 96), (200, 40, 40, 255)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def site_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "site_assets_storage_dir", str(tmp_path))
    monkeypatch.setattr(settings, "outbound_proxy", "")
    return tmp_path


@pytest.fixture
def web(monkeypatch):
    """Serve fake websites through the real pinned fetcher; every name resolves to one public address."""
    monkeypatch.setattr(outbound_target_policy, "_system_resolver", lambda host: [PUBLIC_IP])
    routes: dict[tuple[str, str], tuple[int, dict[str, str], bytes]] = {}
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        status, headers, body = routes.get((request.headers["host"], request.url.path), (404, {}, b""))
        return httpx.Response(status, headers=headers, content=body)

    real_client = httpx.Client
    monkeypatch.setattr(
        tool_website_fetcher.httpx, "Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    return routes, requests


def test_page_icon_is_stored_as_a_local_webp(site_dir, web) -> None:
    routes, requests = web
    routes[("example.com", "/")] = (200, {"content-type": "text/html"}, PAGE)
    routes[("example.com", "/touch.png")] = (200, {"content-type": "image/png"}, _png())

    icon = recommended_website_icons.fetch_recommended_website_icon("https://example.com/")

    assert re.fullmatch(r"/api/media/site/[0-9a-f]{32}\.webp", icon)
    stored = (site_dir / icon.rsplit("/", 1)[1]).read_bytes()
    assert stored[:4] == b"RIFF" and stored[8:12] == b"WEBP"
    assert {request.url.host for request in requests} == {PUBLIC_IP}


def test_redirect_to_a_private_address_is_refused_and_the_favicon_is_used(site_dir, web) -> None:
    routes, requests = web
    routes[("example.com", "/")] = (200, {"content-type": "text/html"}, PAGE)
    routes[("example.com", "/touch.png")] = (302, {"location": "http://127.0.0.1/touch.png"}, b"")
    routes[("example.com", "/favicon.ico")] = (200, {"content-type": "image/x-icon"}, _png())

    icon = recommended_website_icons.fetch_recommended_website_icon("https://example.com/")

    assert icon.endswith(".webp")
    assert [request.url.path for request in requests] == ["/", "/touch.png", "/favicon.ico"]
    assert {request.url.host for request in requests} == {PUBLIC_IP}


def test_svg_and_html_icons_leave_the_monogram(site_dir, web) -> None:
    routes, _ = web
    routes[("example.com", "/")] = (200, {"content-type": "text/html"}, PAGE)
    routes[("example.com", "/touch.png")] = (200, {"content-type": "image/svg+xml"}, SVG)
    routes[("example.com", "/favicon.ico")] = (200, {"content-type": "text/html"}, PAGE)

    assert recommended_website_icons.fetch_recommended_website_icon("https://example.com/") == ""
    assert list(site_dir.iterdir()) == []


def test_unreachable_website_yields_no_icon(site_dir, monkeypatch) -> None:
    def offline(url: str):
        raise tool_website_fetcher.ToolWebsiteFetchError("直接连接和出站代理均无法访问目标网站")

    monkeypatch.setattr(recommended_website_icons, "fetch_tool_website_metadata", offline)
    monkeypatch.setattr(recommended_website_icons, "download_tool_website_image", offline)

    assert recommended_website_icons.fetch_recommended_website_icon("https://example.com/") == ""
    assert list(site_dir.iterdir()) == []


def test_image_download_falls_back_to_the_configured_proxy(monkeypatch) -> None:
    monkeypatch.setattr(tool_website_fetcher.settings, "outbound_proxy", "socks5h://198.51.100.1:1080")
    download = Mock(side_effect=[httpx.ConnectTimeout("offline"), b"icon"])
    monkeypatch.setattr(tool_website_fetcher, "_download_tool_website_image", download)

    assert tool_website_fetcher.download_tool_website_image("https://example.com/favicon.ico") == b"icon"
    assert download.call_args_list[1].kwargs == {"proxy_url": "socks5h://198.51.100.1:1080"}
