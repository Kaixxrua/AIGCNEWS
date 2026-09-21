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


@pytest.fixture(autouse=True)
def no_live_avatar_lookup(monkeypatch):
    monkeypatch.setattr(logos, "resolve_owner_avatars", lambda *args: {})
    monkeypatch.setattr(logos, "resolve_moved_repository_artwork", lambda *args: {})
    monkeypatch.setattr(logos, "_preferred_ips", {})


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


def test_readme_rate_limit_continues_caching_avatars_without_more_api_calls(monkeypatch):
    repository = Mock()
    repository.pending.return_value = [{"repo_id": "a/a", "full_name": "a/a"}, {"repo_id": "b/b", "full_name": "b/b"}]
    calls = []
    def collect(name, api, images, readme_enabled, owner_avatar_url):
        calls.append(readme_enabled)
        return {"status": "found", "content": b"avatar", "readme_rate_limited": True}
    monkeypatch.setattr(logos, "collect_logo", collect)
    result = logos.refresh_project_logos(repository, limit=2, interval=0, workers=1)
    assert result["selected"] == 2 and result["found"] == 2
    assert calls == [True, False]
    assert repository.save.call_count == 2


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


@pytest.mark.parametrize("status,candidates", [
    ("not_found", ()), ("succeeded", ()), ("rate_limited", ()), ("failed", ()),
    ("succeeded", ("https://raw.githubusercontent.com/acme/demo/main/logo.svg",)),
])
def test_missing_or_broken_readme_logo_caches_owner_avatar(monkeypatch, status, candidates):
    from backend.app.services.ingestion import source_github

    monkeypatch.setattr(source_github, "fetch_github_readme_snapshot", lambda *a: SimpleNamespace(
        status=status, logo_candidates=candidates,
    ))
    calls = []
    def download(url, client):
        calls.append(url)
        if "raw.githubusercontent.com" in url:
            raise ValueError("unsupported artwork")
        return b"avatar", "image/webp"
    monkeypatch.setattr(logos, "download_logo", download)
    result = logos.collect_logo("acme/demo", Mock(), Mock())
    assert result["status"] == "found"
    assert result["source_url"] == "https://github.com/acme.png?size=128"
    assert result["content"] == b"avatar"
    assert calls == [*candidates, result["source_url"]]


@pytest.mark.parametrize("host", ["avatars.githubusercontent.com.evil.example", "evil.example"])
def test_avatar_allowlist_is_exact(host):
    with pytest.raises(ValueError):
        logos.logo_url(f"https://{host}/acme?s=128", BASE)


def test_avatar_download_uses_pinning_and_sanitization(monkeypatch):
    from backend.app.services import outbound_target_policy

    monkeypatch.setattr(outbound_target_policy, "_system_resolver", lambda host: ["93.184.216.34"])
    buf = io.BytesIO()
    Image.new("RGB", (128, 128)).save(buf, format="PNG")
    def handler(request):
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "avatars.githubusercontent.com"
        assert "authorization" not in request.headers
        return httpx.Response(200, content=buf.getvalue())
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        body, mime = logos.download_logo("https://avatars.githubusercontent.com/acme?s=128", client)
    assert mime == "image/webp"
    assert Image.open(io.BytesIO(body)).size == (128, 128)



def test_unbounded_daily_collection_drains_multiple_batches(monkeypatch):
    repository = Mock()
    repository.pending.side_effect = [
        [{"repo_id": "a/a", "full_name": "a/a"}],
        [{"repo_id": "b/b", "full_name": "b/b"}], [],
    ]
    monkeypatch.setattr(logos, "collect_logo", lambda *a: {"status": "found"})
    result = logos.refresh_project_logos(repository, limit=0, interval=0)
    assert result["selected"] == 2
    assert repository.save.call_count == 2




def test_official_avatar_redirect_is_pinned_and_downloaded_without_credentials(monkeypatch):
    from backend.app.services import outbound_target_policy

    resolved = []
    def resolve(host):
        resolved.append(host)
        return ['93.184.216.34']
    monkeypatch.setattr(outbound_target_policy, '_system_resolver', resolve)
    seen = []
    def handler(request):
        seen.append(request)
        assert request.url.host == '93.184.216.34'
        assert 'authorization' not in request.headers
        if request.headers['host'] == 'github.com':
            return httpx.Response(302, headers={'location': 'https://avatars.githubusercontent.com/u/314135?s=128&v=4'})
        return httpx.Response(200, content=b'<svg><path d="M0 0h10v10z"/></svg>')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        body, mime = logos.download_logo('https://github.com/cloudflare.png?size=128', client)
    assert mime == 'image/svg+xml' and b'<path' in body
    assert resolved == ['github.com', 'avatars.githubusercontent.com']
    assert len(seen) == 2


@pytest.mark.parametrize('location', [
    'http://avatars.githubusercontent.com/u/1', 'https://127.0.0.1/u/1',
    'https://avatars.githubusercontent.com.evil.example/u/1',
    'https://avatars.githubusercontent.com/cloudflare', 'https://github.com/login',
    'https://user:pass@avatars.githubusercontent.com/u/1',
    'https://avatars.githubusercontent.com:444/u/1', '',
])
def test_avatar_redirect_rejects_untrusted_destinations(monkeypatch, location):
    from backend.app.services import outbound_target_policy

    monkeypatch.setattr(outbound_target_policy, '_system_resolver', lambda host: ['93.184.216.34'])
    handler = Mock(return_value=httpx.Response(302, headers={'location': location}))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            logos.download_logo('https://github.com/cloudflare.png?size=128', client)
    assert handler.call_count == 1


def test_avatar_redirect_revalidates_dns_and_does_not_follow_a_second_redirect(monkeypatch):
    from backend.app.services import outbound_target_policy

    for avatar_ips in (['127.0.0.1'], ['93.184.216.34', '10.0.0.1'], ['93.184.216.34']):
        monkeypatch.setattr(outbound_target_policy, '_system_resolver',
                            lambda host: ['93.184.216.34'] if host == 'github.com' else avatar_ips)
        handler = Mock(return_value=httpx.Response(302, headers={
            'location': 'https://avatars.githubusercontent.com/u/314135?s=128',
        }))
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises((ValueError, httpx.HTTPError)):
                logos.download_logo('https://github.com/cloudflare.png?size=128', client)
        assert handler.call_count == (2 if avatar_ips == ['93.184.216.34'] else 1)


def test_default_avatar_is_rejected_even_when_http_succeeds(monkeypatch):
    import hashlib

    from backend.app.services import outbound_target_policy

    monkeypatch.setattr(outbound_target_policy, '_system_resolver', lambda host: ['93.184.216.34'])
    monkeypatch.setattr(logos, 'sanitize_image', lambda body: (b'placeholder', 'image/webp'))
    monkeypatch.setattr(logos, 'GITHUB_DEFAULT_AVATAR_SHA256', hashlib.sha256(b'placeholder').hexdigest())
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b'image'))) as client:
        with pytest.raises(ValueError, match='default avatar'):
            logos.download_logo('https://avatars.githubusercontent.com/u/1?s=128', client)


def test_unreachable_cdn_edge_uses_another_validated_ip_and_reuses_success(monkeypatch):
    from backend.app.services import outbound_target_policy
    monkeypatch.setattr(outbound_target_policy, '_system_resolver',
                        lambda host: ['185.199.108.133', '185.199.109.133'])
    seen = []
    def handler(request):
        seen.append(request.url.host)
        assert request.extensions['sni_hostname'] == 'avatars.githubusercontent.com'
        if request.url.host == '185.199.108.133':
            raise httpx.ConnectTimeout('unreachable edge')
        return httpx.Response(200, content=b'<svg><path d="M0 0h10v10z"/></svg>')
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        logos.download_logo('https://avatars.githubusercontent.com/u/123?s=128', client)
        logos.download_logo('https://avatars.githubusercontent.com/u/456?s=128', client)
    assert seen == ['185.199.108.133', '185.199.109.133', '185.199.109.133']


def test_cdn_retry_rejects_dns_rebinding_and_does_not_retry_certificate_errors(monkeypatch):
    from backend.app.services import outbound_target_policy
    answers = iter([['185.199.108.133'], ['185.199.109.133', '127.0.0.1']])
    monkeypatch.setattr(outbound_target_policy, '_system_resolver', lambda host: next(answers))
    handler = Mock(side_effect=httpx.ConnectTimeout('unreachable'))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError):
            logos.download_logo('https://avatars.githubusercontent.com/u/123', client)
    assert handler.call_count == 1
    monkeypatch.setattr(outbound_target_policy, '_system_resolver',
                        lambda host: ['185.199.108.133', '185.199.109.133'])
    handler = Mock(side_effect=httpx.ConnectError('CERTIFICATE_VERIFY_FAILED'))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.ConnectError):
            logos.download_logo('https://avatars.githubusercontent.com/u/123', client)
    assert handler.call_count == 1


def test_slow_download_does_not_block_persisting_other_completed_artwork(monkeypatch):
    import threading
    release = threading.Event()
    repository = Mock()
    repository.pending.return_value = [{'repo_id': 'a/slow', 'full_name': 'a/slow'},
                                       {'repo_id': 'b/fast', 'full_name': 'b/fast'}]
    def collect(name, *args):
        if name == 'a/slow':
            assert release.wait(2), 'completed fast artwork was blocked behind a slow request'
        return {'status': 'found'}
    repository.save.side_effect = lambda repo_id, result: release.set() if repo_id == 'b/fast' else None
    monkeypatch.setattr(logos, 'collect_logo', collect)
    assert logos.refresh_project_logos(repository, limit=2, interval=0, workers=2)['found'] == 2


def test_brand_header_and_attachment_logos_without_screenshots():
    attachment = 'https://github.com/ollama/ollama/assets/3325447/0d0b44e2-8f4a-4e99-9b52-a5c1c741c8f7'
    assert logos.discover_logos(f'<img alt="ollama" src="{attachment}">',
                                'https://raw.githubusercontent.com/ollama/ollama/main/README.md') == (attachment,)
    for source in ('hero.png', 'splash.png', 'screenshot.png', 'badge.png'):
        assert not logos.discover_logos(f'![demo]({source})', BASE)
    assert not logos.discover_logos('x' * 1600 + '![demo](header.png)', BASE)
    assert logos.discover_logos('![demo](header.png)', BASE)


def test_svg_local_clip_path_is_supported_external_reference_rejected():
    body, mime = logos.sanitize_image(b'<svg><defs><clipPath id="crop"><rect width="10" height="10"/></clipPath></defs><g clip-path="url(#crop)"><path d="M0 0"/></g></svg>')
    assert b'clipPath' in body and b'url(#crop)' in body and mime == 'image/svg+xml'
    with pytest.raises(ValueError, match='external'):
        logos.sanitize_image(b'<svg><g clip-path="url(https://example.com/crop)"/></svg>')


@pytest.mark.parametrize('destination', ['https://127.0.0.1/logo.png', 'https://example.com/logo.png',
    'https://github-production-user-asset-6210df.s3.amazonaws.com.evil.example/logo.png'])
def test_attachment_redirect_rejects_unapproved_hosts(destination):
    target = SimpleNamespace(request_url='https://93.184.216.34/user-attachments/assets/0d0b44e2-8f4a-4e99-9b52-a5c1c741c8f7',
                             headers={'Host': 'github.com'}, extensions={})
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(302, headers={'location': destination}))) as client:
        with pytest.raises(ValueError):
            logos._download_pinned_logo(target, client)


def test_attachment_cdn_second_redirect_is_rejected():
    target = SimpleNamespace(request_url='https://93.184.216.34/logo.png',
                             headers={'Host': logos._ASSET_CDN}, extensions={})
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(302, headers={'location': 'https://github.com/foo.png'}))) as client:
        with pytest.raises((ValueError, httpx.HTTPStatusError)):
            logos._download_pinned_logo(target, client)


def test_svg_simple_class_styles_are_flattened_with_cascade():
    body, _ = logos.sanitize_image(b'<svg><style>.logo { fill: red; stroke-width: 1px; } #brand {fill: blue} .logo {fill: green}</style><path id="brand" class="logo" d="M0 0"/><path class="logo" style="fill: white"/></svg>')
    assert b'<style' not in body and b'class=' not in body and b'style=' not in body
    assert b'fill="blue"' in body and b'fill="white"' in body and b'stroke-width="1px"' in body


@pytest.mark.parametrize('style', ['@import url(https://evil.example);',
    '.x {fill: url(https://evil.example)}', '.x {fill: expression(alert(1))}',
    '.x {background: red}', 'svg path {fill: red}', '.x {fill: r\\65 d}',
    '@font-face {src: url(https://evil.example)}'])
def test_svg_styles_cannot_load_resources_or_retain_active_css(style):
    with pytest.raises(ValueError):
        logos.sanitize_image(f'<svg><style>{style}</style><path class="x"/></svg>'.encode())


def test_repository_root_paths_and_third_party_logos():
    assert logos.discover_logos('![logo](/assets/logo.svg)', BASE) == (
        'https://raw.githubusercontent.com/acme/demo/main/assets/logo.svg',)
    assert not logos.discover_logos('![Qodo logo](images/qodo-logo.svg)', BASE)
    assert not logos.discover_logos('![TypeScript logo](https://raw.githubusercontent.com/microsoft/TypeScript/main/logo.svg)', BASE)
    assert not logos.discover_logos('![demo](docs/demo_processing.png)', BASE)
    assert not logos.discover_logos('x' * 6100 + '![logo](logo.svg)', BASE)


def test_svg_after_long_xml_comment_is_still_recognized():
    body, mime = logos.sanitize_image(b'<?xml version="1.0"?><!--' + b'x' * 1500 + b'--><svg><path d="M0 0"/></svg>')
    assert mime == 'image/svg+xml' and b'<path' in body


def test_svg_local_reuse_text_and_presentation_styles():
    body, mime = logos.sanitize_image(b'<svg xmlns:xlink="http://www.w3.org/1999/xlink"><metadata><irrelevant/></metadata><defs><path id="mark" d="M0 0"/></defs><use xlink:href="#mark"/><text style="font-size: 12px; fill: rgb(10, 20, 30)">Demo</text></svg>')
    assert mime == 'image/svg+xml' and b'metadata' not in body and b'#mark' in body and b'Demo' in body
    with pytest.raises(ValueError, match='external SVG'):
        logos.sanitize_image(b'<svg><use href="https://evil.example/image.svg#logo"/></svg>')


def test_github_attachment_redirect_revalidates_the_cdn_dns(monkeypatch):
    target = SimpleNamespace(request_url='https://93.184.216.34/user-attachments/assets/0d0b44e2-8f4a-4e99-9b52-a5c1c741c8f7',
                             headers={'Host': 'github.com'}, extensions={})
    pin = Mock(side_effect=ValueError('mixed public/private DNS'))
    monkeypatch.setattr(logos, 'pin_http_target', pin)
    location = 'https://github-production-user-asset-6210df.s3.amazonaws.com/123/logo.png'
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(302, headers={'location': location}))) as client:
        with pytest.raises(ValueError, match='mixed public/private'):
            logos._download_pinned_logo(target, client)
    pin.assert_called_once_with(location, reject_mixed=True, allowed_ports={443})


def test_utf16_svg_and_known_public_doctype_are_normalized_without_external_loading():
    source = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd"><svg><path d="M0 0"/></svg>'
    body, mime = logos.sanitize_image(source.encode('utf-16'))
    assert mime == 'image/svg+xml' and b'DOCTYPE' not in body and b'<path' in body
    with pytest.raises(ValueError):
        logos.sanitize_image('<!DOCTYPE svg [<!ENTITY x "unsafe">]><svg>&x;</svg>'.encode('utf-16'))


def test_static_svg_shadow_is_bounded_and_animated_content_stays_rejected():
    body, _ = logos.sanitize_image(b'<svg><defs><filter id="shadow"><feDropShadow dx="0" dy="1" stdDeviation="2"/></filter></defs><path filter="url(#shadow)"/></svg>')
    assert b'feDropShadow' in body
    for value in ['100000', 'NaN', 'inf', '-1', '2 3 4']:
        with pytest.raises(ValueError):
            logos.sanitize_image(f'<svg><filter><feGaussianBlur stdDeviation="{value}"/></filter></svg>'.encode())
    with pytest.raises(ValueError):
        logos.sanitize_image(b'<svg><animate attributeName="href"/></svg>')


def test_embedded_svg_raster_is_reencoded_but_svg_and_remote_images_are_rejected():
    buf = io.BytesIO()
    Image.new('RGB', (10, 10), 'red').save(buf, format='PNG')
    payload = base64.b64encode(buf.getvalue()).decode()
    body, mime = logos.sanitize_image(f'<svg><image href="data:image/png;base64,{payload}"/></svg>'.encode())
    assert mime == 'image/svg+xml' and b'data:image/webp;base64,' in body and b'data:image/png' not in body
    for payload in [base64.b64encode(b'<svg><path/></svg>').decode(), 'not-valid-base64']:
        with pytest.raises(ValueError):
            logos.sanitize_image(f'<svg><image href="data:image/png;base64,{payload}"/></svg>'.encode())
    with pytest.raises(ValueError):
        logos.sanitize_image(b'<svg><image href="https://127.0.0.1/logo.png"/></svg>')


def test_svg_element_styles_preserve_specificity():
    body, _ = logos.sanitize_image(b'<svg><style>.brand {fill: blue} path {fill: red; isolation: isolate}</style><path class="brand"/></svg>')
    assert b'fill="blue"' in body and b'isolation="isolate"' in body
