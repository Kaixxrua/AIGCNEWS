"""POST /api/ops/site/images 站点公开素材上传端点契约测试。"""

from __future__ import annotations

import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.api.routes_ops import router as ops_router
from backend.app.core.auth import RequireAdmin
from backend.app.core.config import settings

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
PNG_STORE_NAME = hashlib.sha256(PNG_BYTES).hexdigest()[:32] + ".png"


def _client(*, admin: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(ops_router, prefix="/api")
    if admin:
        app.dependency_overrides[RequireAdmin] = lambda: {
            "role": "admin",
            "email": "admin@example.test",
        }
    return TestClient(app)


@pytest.fixture
def site_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "site_assets_storage_dir", str(tmp_path))
    return tmp_path


def test_upload_requires_admin(site_dir) -> None:
    response = _client(admin=False).post(
        "/api/ops/site/images",
        files={"file": ("qr.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code in (401, 403)
    assert list(site_dir.iterdir()) == []


def test_admin_upload_png_stores_content_addressed_file(site_dir) -> None:
    response = _client().post(
        "/api/ops/site/images",
        files={"file": ("qr.png", PNG_BYTES, "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["url"] == f"/api/media/site/{PNG_STORE_NAME}"
    assert body["filename"] == "qr.png"
    assert body["mime_type"] == "image/png"
    assert body["size_bytes"] == len(PNG_BYTES)
    # 落盘文件名只含内容哈希与白名单扩展名，原始文件名不进路径
    assert (site_dir / PNG_STORE_NAME).read_bytes() == PNG_BYTES


def test_reupload_same_content_dedupes_to_same_url(site_dir) -> None:
    client = _client()
    first = client.post("/api/ops/site/images", files={"file": ("a.png", PNG_BYTES, "image/png")})
    second = client.post("/api/ops/site/images", files={"file": ("b.png", PNG_BYTES, "image/png")})

    assert first.status_code == second.status_code == 200
    assert first.json()["url"] == second.json()["url"]
    assert [path.name for path in site_dir.iterdir()] == [PNG_STORE_NAME]


def test_upload_rejects_mime_magic_mismatch(site_dir) -> None:
    response = _client().post(
        "/api/ops/site/images",
        files={"file": ("fake.png", b"\xff\xd8\xff" + b"\x00" * 8, "image/png")},
    )

    assert response.status_code == 400
    assert "不匹配" in response.json()["detail"]


def test_upload_rejects_svg_and_oversize(site_dir) -> None:
    client = _client()

    svg = client.post(
        "/api/ops/site/images",
        files={"file": ("logo.svg", b"<svg></svg>", "image/svg+xml")},
    )
    assert svg.status_code == 400
    assert "仅支持" in svg.json()["detail"]

    oversized = client.post(
        "/api/ops/site/images",
        files={"file": ("big.png", PNG_BYTES + b"x" * (10 * 1024 * 1024), "image/png")},
    )
    assert oversized.status_code == 400
    assert "10 MiB" in oversized.json()["detail"]


def test_media_site_static_mount_registered() -> None:
    """上传产物经 /api/media/site 匿名静态挂载服务（与 papers 树同先例）。"""
    from backend.app.main import app

    mount_paths = {getattr(route, "path", None) for route in app.routes}
    assert "/api/media/site" in mount_paths
