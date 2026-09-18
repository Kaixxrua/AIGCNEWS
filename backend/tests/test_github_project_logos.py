from __future__ import annotations

import base64
import io
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from backend.app.services.ingestion import github_project_logos as logos
from backend.app.services.ingestion.source_github import fetch_github_readme_snapshot

BASE = "https://raw.githubusercontent.com/acme/demo/main/docs/README.md"


def test_candidates_resolve_relative_and_html_without_picking_badges_or_sponsors():
    readme = """
![build](https://img.shields.io/badge/logo.svg)
![screenshot](./screen.png)
![Demo logo](../assets/logo.png)
<img alt="project logo" src="https://github.com/acme/demo/blob/main/logo.svg">
![sponsor logo](./sponsor-logo.png)
![logo](http://127.0.0.1/logo.png)
![logo](https://raw.githubusercontent.com.evil.example/logo.png)
![logo](http://[invalid/logo.svg)
```
![example logo](./fake-logo.png)
```
"""
    assert logos.discover_logos(readme, BASE) == (
        "https://raw.githubusercontent.com/acme/demo/main/assets/logo.png",
        "https://raw.githubusercontent.com/acme/demo/main/logo.svg",
    )


def test_readme_snapshot_exposes_candidates_without_changing_clean_text():
    def handler(request):
        return httpx.Response(200, json={"encoding": "base64", "download_url": BASE,
            "content": base64.b64encode(b"# Demo\n![logo](./logo.png)").decode()})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = fetch_github_readme_snapshot("acme/demo", client)
    assert result.text == "Demo"
    assert result.logo_candidates == ("https://raw.githubusercontent.com/acme/demo/main/docs/logo.png",)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/logo.png", "https://169.254.169.254/logo.png",
    "https://raw.githubusercontent.com:444/logo.png",
    "https://token@raw.githubusercontent.com/acme/logo.png",
    "file:///tmp/logo.svg", "data:image/svg+xml,logo", "https://github.com/login",
])
def test_unsafe_urls_rejected(url):
    with pytest.raises(ValueError):
        logos.logo_url(url, BASE)


@pytest.mark.parametrize("body", [
    b'<svg><script>alert(1)</script></svg>',
    b'<svg><foreignObject/></svg>',
    b'<svg><image href="http://127.0.0.1/x"/></svg>',
    b'<svg><path fill="url(https://evil.example/x)"/></svg>',
    b'<!DOCTYPE svg [<!ENTITY x "x">]><svg>&x;</svg>',
    b'<html>not an image</html>',
    b'x' * (logos.MAX_DOWNLOAD + 1),
])
def test_unsafe_artwork_rejected(body):
    with pytest.raises((ValueError, OSError)):
        logos.sanitize_image(body)


def test_svg_strips_handlers_and_raster_is_reencoded():
    body, mime = logos.sanitize_image(b'<svg xmlns="http://www.w3.org/2000/svg" onload="evil()"><path d="M0 0h10v10z"/></svg>')
    assert mime == "image/svg+xml" and b"onload" not in body and b"<path" in body
    buf = io.BytesIO()
    Image.new("RGB", (800, 400)).save(buf, format="PNG")
    body, mime = logos.sanitize_image(buf.getvalue())
    assert mime == "image/webp"
    assert Image.open(io.BytesIO(body)).size == (256, 128)


def test_download_pins_public_ip_and_does_not_forward_authorization(monkeypatch):
    seen = []
    monkeypatch.setattr(logos, "pin_http_target", lambda *a, **k: SimpleNamespace(
        request_url="https://93.184.216.34/logo.svg",
        headers={"Host": "raw.githubusercontent.com"},
        extensions={"sni_hostname": "raw.githubusercontent.com"},
    ))
    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises((httpx.HTTPError, ValueError)):
            logos.download_logo(BASE, client)
    assert len(seen) == 1
    assert seen[0].headers["host"] == "raw.githubusercontent.com"
    assert "authorization" not in seen[0].headers


def test_rate_limit_stops_batch_and_preserves_unattempted_queue(monkeypatch):
    repository = Mock()
    repository.pending.return_value = [{"repo_id": "a/a", "full_name": "a/a"}, {"repo_id": "b/b", "full_name": "b/b"}]
    monkeypatch.setattr(logos, "collect_logo", lambda *a: {"status": "rate_limited"})
    result = logos.refresh_project_logos(repository, interval=0)
    assert result["selected"] == 1 and result["rate_limited"] == 1
    repository.save.assert_called_once_with("a/a", {"status": "rate_limited"})


def test_collection_downloads_and_hashes_project_logo(monkeypatch):
    from backend.app.services.ingestion import source_github
    monkeypatch.setattr(source_github, "fetch_github_readme_snapshot", lambda *a: SimpleNamespace(
        status="succeeded", logo_candidates=("https://raw.githubusercontent.com/acme/demo/main/logo.svg",),
    ))
    monkeypatch.setattr(logos, "download_logo", lambda *a: (b"sanitized", "image/svg+xml"))
    result = logos.collect_logo("acme/demo", Mock(), Mock())
    assert result["status"] == "found"
    assert result["content"] == b"sanitized"
    assert len(result["sha256"]) == 64
    assert "/logo.svg" in result["source_url"]


def test_wall_clock_budget_leaves_unattempted_queue_untouched(monkeypatch):
    repository = Mock()
    repository.pending.return_value = [{"repo_id": "a/a", "full_name": "a/a"}]
    monkeypatch.setattr(logos, "time", SimpleNamespace(monotonic=Mock(side_effect=[0, 301]), sleep=Mock()))
    assert logos.refresh_project_logos(repository)["selected"] == 0
    repository.save.assert_not_called()


def test_logo_route_is_database_only_and_supports_cache_validation():
    from backend.app.api.routes_github_projects import get_github_logo_repository, router
    repository = Mock()
    repository.get.return_value = {"sha256": "abc", "content": b"safe", "content_type": "image/webp"}
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_github_logo_repository] = lambda: repository
    with TestClient(app) as client:
        response = client.get("/api/projects/github/logo/acme/demo")
        assert response.status_code == 200 and response.content == b"safe"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert "sandbox" in response.headers["content-security-policy"]
        assert client.get("/api/projects/github/logo/acme/demo", headers={"if-none-match": '"abc"'}).status_code == 304
        repository.get.return_value = None
        assert client.get("/api/projects/github/logo/acme/missing").status_code == 404


@pytest.mark.parametrize("addresses", [
    ["127.0.0.1"], ["169.254.169.254"], ["::1"], ["10.0.0.1"],
    ["93.184.216.34", "10.0.0.1"],
])
def test_logo_download_rejects_unsafe_dns_before_request(monkeypatch, addresses):
    from backend.app.services import outbound_target_policy

    monkeypatch.setattr(outbound_target_policy, "_system_resolver", lambda host: addresses)
    client = Mock()
    with pytest.raises(ValueError):
        logos.download_logo(BASE, client)
    client.stream.assert_not_called()


def test_logo_download_rejects_stream_over_limit(monkeypatch):
    from backend.app.services import outbound_target_policy

    monkeypatch.setattr(outbound_target_policy, "_system_resolver", lambda host: ["93.184.216.34"])
    with httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"x" * (logos.MAX_DOWNLOAD + 1)),
    )) as client:
        with pytest.raises(ValueError, match="artwork too large"):
            logos.download_logo(BASE, client)
